"""Fit the frozen-encoder legacy ensemble from matching feature arrays."""
import argparse
from pathlib import Path
import numpy as np
from threadpoolctl import threadpool_limits
from legacy_ensemble import fit


def main():
    p=argparse.ArgumentParser();p.add_argument('--clip-features',type=Path,required=True)
    p.add_argument('--dino-features',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--epochs',type=int,default=800);p.add_argument('--seeds',type=int,default=5);args=p.parse_args()
    with np.load(args.clip_features,allow_pickle=False) as c,np.load(args.dino_features,allow_pickle=False) as d:
        np.testing.assert_array_equal(c['capture_ids'],d['capture_ids']);np.testing.assert_array_equal(c['y'],d['y'])
        x=c['X_clip_full_mean'];views=d['X_views'];y=c['y']
        if len(set(c['capture_ids']))!=len(y):raise ValueError('Duplicate observation IDs')
    with threadpool_limits(limits=1):fit(x,views,y,args.output,epochs=args.epochs,seeds=args.seeds)


if __name__=='__main__':main()
