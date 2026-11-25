"""Per-decoder-call cache of pose-dependent prompt work; token state is never cached."""
from contextlib import contextmanager
from types import MethodType
import torch
import torch.nn.functional as F

def _stamp(t):
    try: version=t._version
    except RuntimeError:return None  # Inference tensors lack mutation counters: use original work.
    return (id(t),version,tuple(t.shape),t.dtype,t.device)

@contextmanager
def install(model,enabled=True):
    stats=dict(computations_2d=0,hits_2d=0,computations_3d=0,hits_3d=0,decoder_calls=0,uncacheable=0)
    if not enabled:yield stats;return
    if model.training:raise ValueError('Prompt cache is inference-only')
    saved=[];scopes={side:dict(active=False,cache={}) for side in ('body','hand')}
    def replace(obj,name,value):
        saved.append((obj,name,name in obj.__dict__,obj.__dict__.get(name)));setattr(obj,name,value)
    def bind_decoder(side):
        decoder=model.decoder if side=='body' else model.decoder_hand;original=decoder.forward;scope=scopes[side]
        def forward(*a,**kw):
            if scope['active']:raise RuntimeError('Concurrent/reentrant decoder calls unsupported')
            scope['active']=True;scope['cache'].clear();stats['decoder_calls']+=1
            try:return original(*a,**kw)
            finally:scope['cache'].clear();scope['active']=False
        replace(decoder,'forward',forward)
    def bind_updates(side):
        suffix='' if side=='body' else '_hand';decoder=model.decoder if side=='body' else model.decoder_hand;scope=scopes[side]
        get=lambda n:getattr(model,n+suffix)
        name2='keypoint_token_update_fn'+suffix;old2=getattr(model,name2)
        name3='keypoint3d_token_update_fn'+suffix;old3=getattr(model,name3)
        def key(pose,image=None):
            tensors=([image,pose['pred_keypoints_2d_cropped'],pose['pred_keypoints_2d_depth']] if image is not None else [pose['pred_keypoints_3d']])
            stamps=[_stamp(t) for t in tensors]
            if any(s is None for s in stamps):stats['uncacheable']+=1;return None
            return (id(pose),tuple(stamps),torch.is_autocast_enabled('cuda'),torch.get_autocast_dtype('cuda'))
        def two(self,start,image,tokens,augment,pose,layer):
            if not scope['active'] or layer==len(decoder.layers)-1:return old2(start,image,tokens,augment,pose,layer)
            # Preserve original clone/add order; cache only values independent of the evolving token state.
            tokens=tokens.clone();augment=augment.clone();n=get('keypoint_embedding').weight.shape[0]
            signature=key(pose,image);entry=scope['cache'].get('2d')
            if signature is not None and entry is not None and signature==entry['key']:
                pe,delta=entry['pe'],entry['delta'];stats['hits_2d']+=1
            else:
                xy=pose['pred_keypoints_2d_cropped'].clone()[:,get('keypoint_embedding_idxs')]
                depth=pose['pred_keypoints_2d_depth'].clone()[:,get('keypoint_embedding_idxs')]
                xy01=xy+.5
                invalid=(xy01[:,:,0]<0)|(xy01[:,:,0]>1)|(xy01[:,:,1]<0)|(xy01[:,:,1]>1)|(depth<1e-5)
                pe=get('keypoint_posemb_linear')(xy)*(~invalid[:,:,None]);points=xy*2
                if model.cfg.MODEL.BACKBONE.TYPE in ['vit_hmr','vit','vit_b','vit_l','vit_hmr_512_384']:
                    points[:,:,0]=points[:,:,0]/12*16
                feat=F.grid_sample(image,points[:,:,None,:],mode='bilinear',padding_mode='zeros',align_corners=False).squeeze(3).permute(0,2,1)
                feat=feat*(~invalid[:,:,None]);delta=get('keypoint_feat_linear')(feat);stats['computations_2d']+=1
                if signature is not None:scope['cache']['2d']=dict(key=signature,pe=pe,delta=delta,refs=(pose,image))
            augment[:,start:start+n,:]=pe;tokens=tokens.clone();tokens[:,start:start+n,:]+=delta
            return tokens,augment,pose,layer
        def three(self,start,tokens,augment,pose,layer):
            if not scope['active'] or layer==len(decoder.layers)-1:return old3(start,tokens,augment,pose,layer)
            n=get('keypoint3d_embedding').weight.shape[0];signature=key(pose);entry=scope['cache'].get('3d')
            if signature is not None and entry is not None and signature==entry['key']:
                pe=entry['pe'];stats['hits_3d']+=1
            else:
                xyz=pose['pred_keypoints_3d'].clone()
                xyz=xyz-(xyz[:,[model.pelvis_idx[0]],:]+xyz[:,[model.pelvis_idx[1]],:])/2
                xyz=xyz[:,get('keypoint3d_embedding_idxs')];pe=get('keypoint3d_posemb_linear')(xyz);stats['computations_3d']+=1
                if signature is not None:scope['cache']['3d']=dict(key=signature,pe=pe,refs=pose)
            augment=augment.clone();augment[:,start:start+n,:]=pe
            return tokens,augment,pose,layer
        replace(model,name2,MethodType(two,model));replace(model,name3,MethodType(three,model))
    try:
        for side in ('body','hand'):bind_decoder(side);bind_updates(side)
        yield stats
    finally:
        for scope in scopes.values():scope['cache'].clear();scope['active']=False
        for obj,name,own,value in reversed(saved):
            if own:setattr(obj,name,value)
            else:delattr(obj,name)
