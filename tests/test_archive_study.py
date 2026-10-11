import json
import zipfile
import numpy as np
import pytest
from studio.archive_study import safe_extract, find_groups


def test_archive_paths_checked_before_extraction(tmp_path):
    p=tmp_path/'unsafe.zip'
    with zipfile.ZipFile(p,'w') as z:
        z.writestr('good.txt','source')
        z.writestr('../outside.txt','escape')
    with pytest.raises(ValueError):safe_extract(p,tmp_path/'source')
    assert not (tmp_path/'source/good.txt').exists()
    assert not (tmp_path/'outside.txt').exists()


def test_archive_duplicate_member_rejected(tmp_path):
    p=tmp_path/'duplicate.zip'
    with zipfile.ZipFile(p,'w') as z:
        z.writestr('same','a')
        with pytest.warns(UserWarning):z.writestr('same','b')
    with pytest.raises(ValueError):safe_extract(p,tmp_path/'source')


def test_groups_use_numeric_scan_order_and_preserve_partial_panels(tmp_path):
    for n in (11,2,0,1,10):
        path=tmp_path/f'gel_sight_data/collection/panel_2/scan_{n}/metadata.json'
        path.parent.mkdir(parents=True);path.write_text(json.dumps(dict(panel=2,scan=n)))
    groups=find_groups(tmp_path)
    assert [n for n,_,_ in groups['collection/panel_2']]==[0,1,2,10,11]
    p=tmp_path/'gel_sight_data/collection/panel_2/scan_0/metadata.json'
    p.write_text(json.dumps(dict(panel=1,scan=0)))
    with pytest.raises(ValueError):find_groups(tmp_path)
