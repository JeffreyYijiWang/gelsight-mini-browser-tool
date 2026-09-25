from __future__ import annotations
import argparse
import json
import os
from pathlib import Path


def main():
    # Match worker budgets in the owner server/CLI too. Large automatic BLAS
    # thread pools can exhaust Windows commit memory alongside a camera browser.
    for variable in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS'):
        os.environ.setdefault(variable,'2')
    parser=argparse.ArgumentParser(description='GelSight Material Studio: local processing and dictionary publication builds.')
    parser.add_argument('command',choices=['serve','worker','demo','run','import','build-dictionary','examples','train-calibration'])
    parser.add_argument('--data',default='studio-data')
    parser.add_argument('--port',type=int,default=8090)
    parser.add_argument('--job')
    parser.add_argument('--kind')
    parser.add_argument('--config',type=Path)
    parser.add_argument('--input',type=Path)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    if args.command=='serve':
        import uvicorn
        from .api import create_app
        uvicorn.run(create_app(args.data),host='127.0.0.1',port=args.port)
        return
    from .store import Store
    store=Store(args.data)
    settings=json.loads(args.config.read_text(encoding='utf-8')) if args.config else {}
    if args.command=='worker':
        from .jobs import worker
        worker(args.data,args.job);return
    if args.command=='demo':
        from .inputs import synthetic_demo
        result=synthetic_demo(store,**settings)
    elif args.command=='run':
        from .jobs import dispatch
        result=dispatch(store,args.kind,settings,lambda v,m:print(f'{v:.0%} {m}',flush=True))
    elif args.command=='import':
        from .inputs import import_bytes,import_video,IMAGE_EXTENSIONS
        if not args.input:parser.error('--input is required')
        files=sorted(p for p in args.input.iterdir() if p.suffix.lower() in IMAGE_EXTENSIONS|{'.npy','.npz'}) if args.input.is_dir() else [args.input]
        result=[];session=None
        for path in files:
            if path.suffix.lower() in ('.mp4','.mov','.mkv','.avi','.webm'):
                item=import_video(store,path.name,path.read_bytes(),settings)
            else:item=import_bytes(store,path.name,path.read_bytes(),args.kind or 'rgb',session,settings)
            session=item.get('session',{}).get('id');result.append(item)
    elif args.command=='build-dictionary':
        from .dictionary import build_dictionary
        result=build_dictionary(store,args.output or Path('texture-dictionary/dist'),**settings)
    elif args.command=='examples':
        from .examples import generate_examples
        result=generate_examples(store,args.output or Path('examples/generated'))
    elif args.command=='train-calibration':
        from .training import train_polynomial
        if not args.input or not args.output:parser.error('--input and --output are required')
        result=train_polynomial(args.input,args.output,**settings)
    else:return
    print(json.dumps(result,indent=2,allow_nan=False))


if __name__=='__main__':main()
