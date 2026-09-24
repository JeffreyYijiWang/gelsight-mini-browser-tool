"""Bounded subprocess jobs: cancellation terminates computation, not just polling."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

from .records import uid, now
from .store import Store

KINDS={"demo","reconstruct","derive","analyze","material","atlas","print","project_mesh","impression","typology","typology_export","dictionary_preview","dictionary_build","exhibition_export","texture_export","gallery_export","atlas_export","print_export","video"}


def dispatch(store,kind,params,progress=None):
    if kind=="typology":
        from .typology import build_typology
        return build_typology(store,params['items'],params.get('name','Texture typology'),params.get('settings'),progress)
    if kind=="typology_export":
        from .materials import zip_directory
        record=store.get('typologies',params['id'])
        return zip_directory(store,'private-typology',[record['id']],store.path(record['directory']))
    if kind=="demo":
        from .inputs import synthetic_demo
        return synthetic_demo(store,**params)
    if kind=="reconstruct":
        from .reconstruction import reconstruct
        return reconstruct(store,params["frame_id"],params.get("settings"),progress)
    if kind=="derive":
        from .materials import derive_patch
        return derive_patch(store,params["patch_id"],params.get("settings",{}))
    if kind=="analyze":
        from .materials import analyze_patch
        return analyze_patch(store,params["patch_id"],params.get("settings"))
    if kind=="material":
        from .materials import build_material
        return build_material(store,params["patch_id"],params.get("settings"),progress)
    if kind=="atlas":
        from .atlas import build_atlas
        if params.get("settings",{}).get("reconstruct_frames"):
            from .reconstruction import reconstruct
            for frame_id in params["frame_ids"]:
                reconstruct(store,frame_id,params.get("reconstruction_settings"),progress)
        return build_atlas(store,params["frame_ids"],params.get("settings"),progress)
    if kind=="print":
        from .printing import make_print
        return make_print(store,params["source_id"],params.get("settings"),progress)
    if kind=="project_mesh":
        from .printing import project_mesh_to_patch
        return project_mesh_to_patch(store,params["frame_id"],params.get("settings",{}))
    if kind=="impression":
        from .ink import create_impression
        return create_impression(store,params["specimen_id"],params.get("settings"),progress)
    if kind=="dictionary_preview":
        from .dictionary import build_dictionary
        preview_id=uid();output=store.path('previews/'+preview_id)
        result=build_dictionary(store,output,preview_ids=params["specimen_ids"],branding=params.get("branding"))
        result["url"]=f"/api/previews/{preview_id}/";return result
    if kind=="dictionary_build":
        from .dictionary import build_dictionary
        root=Path(__file__).resolve().parents[1]
        return build_dictionary(store,root/'texture-dictionary/dist',branding=params.get("branding"),origin=params.get("origin"))
    if kind=="texture_export":
        from .materials import export_textures
        return export_textures(store,params["material_id"])
    if kind=="exhibition_export":
        from .dictionary import export_exhibition
        return export_exhibition(store,params.get('specimen_ids'),params.get('branding'))
    if kind=="gallery_export":
        from .materials import export_gallery
        return export_gallery(store,params["material_ids"])
    if kind in ("atlas_export","print_export"):
        from .materials import zip_directory
        kind_name="atlases" if kind=="atlas_export" else "prints"
        record=store.get(kind_name,params["id"])
        directory=store.path(f"atlases/{record['id']}" if kind_name=="atlases" else record["directory"])
        return zip_directory(store,kind,[record["id"]],directory)
    if kind=="video":
        from .inputs import import_video
        return import_video(store,params["name"],store.path(params["raw_file"]).read_bytes(),params.get("settings"),progress)
    raise ValueError("Unknown processing job.")


def worker(root,job_id):
    store=Store(root);job=store.get("jobs",job_id);last=[0.]
    def progress(value,message):
        if time.monotonic()-last[0]<.2:return
        last[0]=time.monotonic();job.update(progress=min(.99,float(value)),message=message,status="running")
        store.save("jobs",job)
    job.update(status="running",message="Starting CPU processing",started_at=now());store.save("jobs",job)
    try:
        result=dispatch(store,job["kind"],job["params"],progress)
        job.update(status="completed",progress=1.,message="Completed",result=result,finished_at=now())
    except Exception as exc:
        job.update(status="failed",message=str(exc),error_type=type(exc).__name__,finished_at=now())
    store.save("jobs",job)


def process_memory(pid):
    if sys.platform=="win32":
        import ctypes
        from ctypes import wintypes
        class Counters(ctypes.Structure):
            _fields_=[("cb",wintypes.DWORD),("PageFaultCount",wintypes.DWORD)]+[(name,ctypes.c_size_t) for name in ("PeakWorkingSetSize","WorkingSetSize","QuotaPeakPagedPoolUsage","QuotaPagedPoolUsage","QuotaPeakNonPagedPoolUsage","QuotaNonPagedPoolUsage","PagefileUsage","PeakPagefileUsage")]
        kernel=ctypes.WinDLL('kernel32',use_last_error=True);psapi=ctypes.WinDLL('psapi',use_last_error=True)
        kernel.OpenProcess.restype=wintypes.HANDLE;kernel.CloseHandle.argtypes=[wintypes.HANDLE]
        psapi.GetProcessMemoryInfo.argtypes=[wintypes.HANDLE,ctypes.POINTER(Counters),wintypes.DWORD]
        handle=kernel.OpenProcess(0x410,False,pid)
        if not handle:return 0
        try:
            counters=Counters();counters.cb=ctypes.sizeof(counters)
            return counters.WorkingSetSize if psapi.GetProcessMemoryInfo(handle,ctypes.byref(counters),counters.cb) else 0
        finally:kernel.CloseHandle(handle)
    path=Path(f'/proc/{pid}/status')
    if path.exists():
        for line in path.read_text().splitlines():
            if line.startswith('VmRSS:'):return int(line.split()[1])*1024
    return 0


class Jobs:
    def __init__(self,store,max_jobs=2,memory_mb=2048):
        self.store=store;self.max_jobs=max_jobs;self.memory_mb=memory_mb;self.processes={};self.lock=threading.Lock()
        for old in store.list("jobs"):
            if old['status'] in ('running','queued'):
                old.update(status="interrupted",message="Server restarted; submit the operation again.");store.save('jobs',old)

    def start(self,kind,params):
        if kind not in KINDS:raise ValueError("Unknown job type.")
        with self.lock:
            if sum(p.poll() is None for p in self.processes.values())>=self.max_jobs:raise ValueError("Two jobs are already running. Wait or cancel one before starting another.")
            job={"id":uid(),"kind":kind,"params":params,"status":"queued","progress":0.,"message":"Queued","created_at":now(),"memory_limit_mb":self.memory_mb}
            self.store.save("jobs",job)
            env={**os.environ,"OPENBLAS_NUM_THREADS":"2","OMP_NUM_THREADS":"2"}
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform=='win32' else 0
            process=subprocess.Popen([sys.executable,'-m','studio','worker','--data',str(self.store.root),'--job',job['id']],cwd=Path(__file__).resolve().parents[1],
                                     env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=creationflags)
            self.processes[job['id']]=process
            threading.Thread(target=self._monitor,args=(job['id'],process),daemon=True).start()
            return job

    def _monitor(self,job_id,process):
        started=time.monotonic()
        while process.poll() is None:
            if process_memory(process.pid)>self.memory_mb*1024**2:
                self.cancel(job_id,"Memory budget exceeded; crop the source or lower mesh/atlas resolution.");return
            if time.monotonic()-started>1800:
                self.cancel(job_id,"30-minute compute budget exceeded; reduce the job size.");return
            time.sleep(.5)
        job=self.store.get('jobs',job_id)
        if job['status'] in ('queued','running'):
            job.update(status='failed',message=f"Processing exited unexpectedly ({process.returncode}). Check input size and model dependencies.")
            self.store.save('jobs',job)

    def cancel(self,job_id,message="Cancelled by owner"):
        process=self.processes.get(job_id)
        if process and process.poll() is None:
            process.terminate();process.wait(timeout=10)
        job=self.store.get('jobs',job_id)
        if job['status'] in ('queued','running'):
            job.update(status='cancelled',message=message,finished_at=now());self.store.save('jobs',job)
        return job

    def close(self):
        for job_id in list(self.processes):self.cancel(job_id,"Server shutting down")
