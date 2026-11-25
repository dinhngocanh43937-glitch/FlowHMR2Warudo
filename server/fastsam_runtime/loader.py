"""Fast-SAM-3D-Body checkpoint-compatible feature adapter; no production package changes."""
import pathlib,sys,os,types,torch
P=pathlib.Path(__file__).resolve().parent/'fast_impl'

def activate():
 os.environ.update(USE_COMPILE='0',USE_COMPILE_BACKBONE='0',USE_TRT_BACKBONE='0',LAYER_DTYPE='fp32',MOMENTUM_ENABLED='0',MHR_USE_CUDA_GRAPH='0',DEBUG_NAN='0',INTERM_TIMING='0',DEBUG_BACKBONE_INPUT='0',FAST_SAM_DEBUG_SYNC='0',IMG_SIZE='512')
 for key in ['BODY_INTERM_PRED_LAYERS','HAND_INTERM_PRED_LAYERS','INTERM_PRED_LAYERS','INTERM_PRED_INTERVAL','BODY_INTERM_PRED_INTERVAL','HAND_INTERM_PRED_INTERVAL']:os.environ.pop(key,None)
 from persona_flowhmr.paths import bootstrap_runtime
 bootstrap_runtime();sys.path.insert(0,str(P/'vendor'))
 if 'sam_3d_body' in sys.modules and not pathlib.Path(sys.modules['sam_3d_body'].__file__).is_relative_to(P/'vendor'):raise RuntimeError('Original SAM package already imported; launch Fast in a fresh process')
 import sam_3d_body
 assert pathlib.Path(sam_3d_body.__file__).is_relative_to(P/'vendor')
 return str(sam_3d_body.__file__)

def adapt_model(model,*,no_correctives=False,compile_slim=False):
 # Expose upstream Fast's minimal intermediate output through the old _keypoints_only head contract.
 for head in [model.head_pose,model.head_pose_hand]:
  head.apply_correctives=not no_correctives;original=head.forward
  def make(h,old):
   def forward(x,init_estimate=None,*a,**kw):
    if not getattr(h,'_keypoints_only',False):return old(x,init_estimate,*a,**kw)
    rot,pose,j3d=h._head_forward_core_slim(x,init_estimate)
    return dict(pred_pose_raw=torch.cat([rot,pose],dim=1),pred_keypoints_3d=j3d,pred_vertices=None,pred_joint_coords=None,pred_pose_rotmat=None)
   return forward
  head.forward=make(head,original)
 if compile_slim:
  model._interm_compiled=True;model._use_slim_interm=True
  model._compiled_interm_pred_body=model._interm_pred_body_core;model._compiled_interm_pred_hand=model._interm_pred_hand_core
  model._compiled_interm_pred_body_slim=torch.compile(model._interm_pred_body_core_slim,fullgraph=False,dynamic=False,options={'triton.cudagraphs':False})
  model._compiled_interm_pred_hand_slim=torch.compile(model._interm_pred_hand_core_slim,fullgraph=False,dynamic=False,options={'triton.cudagraphs':False})
 return model
