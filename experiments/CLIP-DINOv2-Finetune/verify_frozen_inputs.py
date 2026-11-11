"""Verify every reused mask without changing images, targets, or database."""
import json
from pathlib import Path
import numpy as np
from PIL import Image
from train import BASE, write_json


def main():
    run=BASE/'outputs'/'frozen_views_20261111'
    manifest=json.loads((run/'manifest.private.json').read_text(encoding='utf-8'))
    checked=0
    for row in manifest['samples']:
        for view in row['views']:
            folder=Path(view['sam']).parent
            metadata=json.loads((folder.parent/'metadata.json').read_text(encoding='utf-8'))
            instance=next(i for i in metadata['instances'] if Path(i['output_directory'])==folder)
            with Image.open(folder/'mask.png') as image:mask=np.asarray(image.convert('L'))>0
            with Image.open(view['sam']) as image:seg=np.asarray(image.convert('RGB'))
            with Image.open(view['crop']) as image:crop=np.asarray(image.convert('RGB'))
            assert seg.shape==crop.shape and mask.shape==seg.shape[:2]
            assert mask.any() and int(mask.sum())==instance['mask_pixels']
            assert np.all(seg[~mask]==0) and np.array_equal(seg[mask],crop[mask])
            assert metadata['camera']==view['camera'] and metadata['source'].casefold()==view['original'].casefold()
            checked+=1
    assert checked==manifest['all_available_sam_frames']
    report={'passed':True,'mask_frames_checked':checked,'sample_groups':len(manifest['samples']),
            'empty_masks':0,'segmented_pixels_match_crop_and_mask':True,'no_added_black_placeholder_views':True,
            'database_modified':False,'note':'File integrity only, not expert mask boundary validation.'}
    write_json(run/'input_verification.json',report);print(json.dumps(report),flush=True)


if __name__=='__main__':main()
