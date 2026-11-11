"""RGB-only numeric phenotype inference; no target CSV/PLY is read."""
import argparse
import csv
import json
from pathlib import Path
from legacy_ensemble import choose_views,extract_features,load,predict_features


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--model',type=Path,required=True)
    parser.add_argument('--image-folder',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--clip-cache',type=Path);parser.add_argument('--dino-repo',type=Path);parser.add_argument('--dino-weights',type=Path)
    parser.add_argument('--device',choices=['cpu','cuda']);args=parser.parse_args()
    model=load(args.model);paths=choose_views(args.image_folder)
    cf,df=extract_features(paths,args.clip_cache,args.dino_repo,args.dino_weights,args.device)
    values=predict_features(model,cf,df)[0];predictions=dict(zip(model['metadata']['target_names'],map(float,values)))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(predictions));writer.writeheader();writer.writerow(predictions)
    result={'predictions':predictions,'images_used':24,'label_schema':'VENDOR_NATIVE',
            'coordinate_unit':'VENDOR_UNIT_UNVERIFIED','target_csv_or_ply_read':False,'point_cloud_generated':False}
    args.output.with_suffix('.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result),flush=True)


if __name__=='__main__':main()
