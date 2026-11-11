"""Original fixed 50/50 frozen CLIP + DINO selector phenotype ensemble.

Backbones remain frozen. Only PCA/Ridge and five small selectors are fitted.
"""
import json
import random
from pathlib import Path
import joblib
import numpy as np
import torch
from torch import nn
from sklearn.decomposition import PCA
from sklearn.linear_model import RidgeCV
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

TARGETS=['pGH','pTLA','pPLA','pLAA','pCHA','pE','pMW']


class ViewSelector(nn.Module):
    def __init__(self,feature_count,output_count=7):
        super().__init__()
        self.camera=nn.Embedding(4,3);self.role=nn.Embedding(2,2);self.angle=nn.Embedding(6,3)
        self.score=nn.Sequential(nn.Linear(feature_count+8,12),nn.Tanh(),nn.Linear(12,1))
        self.head=nn.Linear(feature_count*3,output_count)
    def forward(self,x,camera,role,angle,mask=None):
        metadata=torch.cat([self.camera(camera),self.role(role),self.angle(angle)],dim=-1)
        metadata=metadata.unsqueeze(0).expand(x.shape[0],-1,-1)
        scores=self.score(torch.cat([x,metadata],dim=-1)).squeeze(-1)
        if mask is not None:scores=scores.masked_fill(~mask,-1e4)
        weights=torch.softmax(scores,dim=1)
        selected=(weights.unsqueeze(-1)*x).sum(dim=1)
        top=x[:,role==0].mean(dim=1);side=x[:,role==1].mean(dim=1)
        return self.head(torch.cat([selected,top,side],dim=-1)),weights


def fit(clip_means,dino_views,y,output,epochs=800,seeds=5,device=None):
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    clip_means=np.asarray(clip_means);dino_views=np.asarray(dino_views,dtype=np.float64);y=np.asarray(y,dtype=np.float64)
    assert clip_means.shape==(len(y),512) and dino_views.shape==(len(y),24,384) and y.shape[1]==7
    device=torch.device(device or ('cuda' if torch.cuda.is_available() else 'cpu'))
    mean=y.mean(0);scale=y.std(0);scale[scale==0]=1.
    regressors=[]
    for j in range(y.shape[1]):
        regressor=Pipeline([('scale',StandardScaler()),('pca',PCA(n_components=min(5,len(y)-1),svd_solver='full')),
                            ('ridge',RidgeCV(alphas=np.logspace(-3,3,13)))])
        regressor.fit(clip_means,(y[:,j]-mean[j])/scale[j]);regressors.append(regressor)
    k=min(12,len(y)-1,dino_views.shape[-1])
    pca=PCA(n_components=k,whiten=True,random_state=0).fit(dino_views.reshape(-1,384))
    x=torch.as_tensor(pca.transform(dino_views.reshape(-1,384)).reshape(len(y),24,-1),dtype=torch.float32,device=device)
    camera=torch.tensor(np.repeat(np.arange(4),6),dtype=torch.long,device=device)
    role=(camera>=2).long();angle=torch.tensor(np.tile(np.arange(6),4),dtype=torch.long,device=device)
    target=torch.tensor((y-mean)/scale,dtype=torch.float32,device=device)
    states=[];losses=[]
    for seed in range(seeds):
        random.seed(seed);np.random.seed(seed);torch.manual_seed(seed);torch.cuda.manual_seed_all(seed)
        model=ViewSelector(k).to(device);optimizer=torch.optim.AdamW(model.parameters(),lr=.01,weight_decay=.05)
        for epoch in range(epochs):
            generator=torch.Generator(device=device).manual_seed(seed*epochs+epoch)
            keep=torch.rand((len(y),24),generator=generator,device=device)>.20;keep[:,0]=True
            noise=torch.randn(x.shape,generator=generator,device=device)*.015
            pred,_=model(x+noise,camera,role,angle,keep)
            loss=nn.functional.smooth_l1_loss(pred,target)
            if not torch.isfinite(loss):raise RuntimeError('Non-finite selector loss')
            optimizer.zero_grad(set_to_none=True);loss.backward();optimizer.step()
        states.append({name:p.detach().cpu().clone() for name,p in model.state_dict().items()})
        losses.append(float(loss.detach()));print(f'seed={seed} full_fit_loss={losses[-1]:.6f}',flush=True)
    joblib.dump({'clip_regressors':regressors,'dino_pca':pca,'target_mean':mean,'target_scale':scale},output/'regressors.joblib',compress=3)
    torch.save({'selector_states':states},output/'selectors.pt')
    metadata={'model_family':'frozen_clip_dinov2_legacy_ensemble','target_names':TARGETS,'samples':len(y),
              'selector_components':k,'epochs':epochs,'seeds':seeds,'fixed_clip_weight':.5,'backbones_updated':False,
              'preprocessing':'CLIP official transform; DINO Resize256/CenterCrop224/ImageNet normalization',
              'views':'4 cameras, 6 ordered acquisition positions per camera, 24 full-frame RGB images',
              'coordinate_unit':'VENDOR_UNIT_UNVERIFIED','label_schema':'VENDOR_NATIVE','full_data_fit':True,
              'held_out_score_from_this_fit':None,'training_losses_not_validation_scores':losses}
    (output/'model.json').write_text(json.dumps(metadata,indent=2),encoding='utf-8')
    return load(output)


def load(folder):
    folder=Path(folder);metadata=json.loads((folder/'model.json').read_text(encoding='utf-8'))
    payload=joblib.load(folder/'regressors.joblib')
    states=torch.load(folder/'selectors.pt',map_location='cpu',weights_only=True)['selector_states']
    models=[]
    for state in states:
        model=ViewSelector(metadata['selector_components']);model.load_state_dict(state,strict=True);model.eval();models.append(model)
    return {'metadata':metadata,**payload,'selectors':models}


def predict_features(model,clip_means,dino_views):
    clip_means=np.asarray(clip_means);dino_views=np.asarray(dino_views,dtype=np.float64)
    if clip_means.ndim==1:clip_means=clip_means[None]
    if dino_views.ndim==2:dino_views=dino_views[None]
    assert dino_views.shape[1:]==(24,384) and len(clip_means)==len(dino_views)
    mean=model['target_mean'];scale=model['target_scale']
    cp=np.stack([r.predict(clip_means)*scale[j]+mean[j] for j,r in enumerate(model['clip_regressors'])],axis=1)
    x=torch.tensor(model['dino_pca'].transform(dino_views.reshape(-1,384)).reshape(len(dino_views),24,-1),dtype=torch.float32)
    camera=torch.tensor(np.repeat(np.arange(4),6),dtype=torch.long);role=(camera>=2).long();angle=torch.tensor(np.tile(np.arange(6),4),dtype=torch.long)
    with torch.inference_mode():dp=np.mean([selector(x,camera,role,angle)[0].numpy()*scale+mean for selector in model['selectors']],axis=0)
    return .5*cp+.5*dp


def choose_views(folder):
    folder=Path(folder);result=[]
    for camera in range(1,5):
        files=sorted(p for p in folder.glob(f'CAM{camera}_*') if p.suffix.lower() in ('.jpg','.jpeg','.png'))
        if len(files)<6:raise ValueError(f'CAM{camera}: at least six images required, got {len(files)}')
        result.extend(files[round(i*(len(files)-1)/5)] for i in range(6))
    return result


def extract_features(paths,clip_cache=None,dino_repo=None,dino_weights=None,device=None):
    import clip
    from PIL import Image
    from torchvision import transforms
    if len(paths)!=24:raise ValueError('Exactly 24 ordered views required')
    device=device or ('cuda' if torch.cuda.is_available() else 'cpu')
    clip_model,preprocess=clip.load('ViT-B/32',device=device,jit=False,download_root=str(clip_cache) if clip_cache else None)
    if dino_repo:
        if not dino_weights:raise ValueError('Local DINO source requires --dino-weights')
        dino=torch.hub.load(str(dino_repo),'dinov2_vits14',source='local',pretrained=False)
        dino.load_state_dict(torch.load(dino_weights,map_location='cpu',weights_only=True),strict=True)
    else:dino=torch.hub.load('facebookresearch/dinov2','dinov2_vits14',pretrained=True,trust_repo=True)
    dino=dino.to(device).eval();clip_model.eval()
    for model in (clip_model,dino):
        for parameter in model.parameters():parameter.requires_grad_(False)
    transform=transforms.Compose([transforms.Resize(256,interpolation=transforms.InterpolationMode.BICUBIC),
        transforms.CenterCrop(224),transforms.ToTensor(),transforms.Normalize((.485,.456,.406),(.229,.224,.225))])
    clip_features=[];dino_inputs=[]
    with torch.inference_mode():
        for start in range(0,24,6):
            batch=[]
            for path in paths[start:start+6]:
                with Image.open(path) as image:
                    image=image.convert('RGB');batch.append(preprocess(image));dino_inputs.append(transform(image))
            clip_features.append(clip_model.encode_image(torch.stack(batch).to(device)).float().cpu().numpy())
        df=torch.nn.functional.normalize(dino(torch.stack(dino_inputs).to(device)).float(),dim=-1).cpu().numpy()
    return np.concatenate(clip_features).mean(0),df
