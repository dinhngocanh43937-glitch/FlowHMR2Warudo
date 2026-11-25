'use strict';
const $=id=>document.getElementById(id),key=document.querySelector('meta[name="ui-key"]').content;
const phaseNames={preprocessing:'本机视频预处理中',connecting:'连接输入中',warming_up:'模型加载与编译预热',buffering:'首帧缓冲中',streaming:'实时推理中',stopped:'等待采集',stopping:'正在停止',waiting_previous:'等待上一轮推理结束',reconnecting:'等待重连'};
let kind='video',selectedVideo='',lastSnapshot=null,previewURL='',busy=false;
const frozenPreview=new FrozenPreview(session=>fetch('/api/preview',{headers:{'X-UI-Key':key,'X-Preview-Session':session}}),blob=>{const next=URL.createObjectURL(blob);$('preview').src=next;$('preview').style.display='block';$('previewEmpty').hidden=true;if(previewURL)URL.revokeObjectURL(previewURL);previewURL=next;},()=>{if(previewURL)URL.revokeObjectURL(previewURL);previewURL='';$('preview').removeAttribute('src');$('preview').style.display='none';$('previewEmpty').hidden=false;});
let pollTimer=null,pollBusy=false,pollAgain=false,lastEventsKey='';
let parameterLoaded=null,parameterDirty=false,parameterBusy=false;
const parameterFields={target_fps:'paramTargetFps',sam_stride:'paramSamStride',body_decoder_layers:'paramBodyLayers',ode_steps:'paramSteps',yolo_size:'paramYolo',hand_mode:'paramHandMode',hand_decoder_layers:'paramHandLayers'};
const num=(v,d=1)=>v===null||v===undefined||!Number.isFinite(Number(v))?'—':Number(v).toFixed(d);
const val=(id,v)=>{const node=$(id),text=String(v);if(node.textContent!==text)node.textContent=text;};
const unitVal=(id,v,unit)=>{const node=$(id),text=String(v);if(node.textContent!==text+unit)node.replaceChildren(document.createTextNode(text),Object.assign(document.createElement('small'),{textContent:unit}));};
async function api(path,data){let options={headers:{'X-UI-Key':key}};if(data!==undefined){options.method='POST';options.headers['Content-Type']='application/json';options.body=JSON.stringify(data)}const r=await fetch(path,options),j=await r.json();if(!r.ok)throw new Error(j.error||`HTTP ${r.status}`);return j}
function toast(text){val('toast',text);$('toast').hidden=false;setTimeout(()=>$('toast').hidden=true,4500)}
function render(s){lastSnapshot=s;const c=s.client,r=s.receiver,remote=s.server||{},t=remote.telemetry||{},cfg={...(remote.config||{}),...(remote.parameters?.values||{})},n=remote.network_input||{},g=remote.gpu||{},device=g.devices?.[0],live=s.server_online&&s.metrics_age_s<5,active=c.thread_active;
 frozenPreview.observe(c);
 syncParameters(remote.parameters);
 if(!selectedVideo&&c.kind==='video'&&/^[0-9a-f]{24}\.(mp4|mov|avi|mkv|webm|m4v)$/i.test(c.source_name||'')){selectedVideo=c.source_name.replace(/\.[^.]+$/,'');$('videoPath').value=c.source_name;}
 if(c.state==='preprocessing')val('fileHint',`正在本机预处理 ${num(c.preprocess_percent||0,0)}% · 可点击停止取消 · 尚未上传`);else if(c.prepared_video)val('fileHint',`已预处理 ${c.prepared_video.width}×${c.prepared_video.height} · 30 FPS · H.264${c.prepared_video.reused?' · 已复用兼容文件/缓存':''}`);
 val('endpoint',s.endpoint);val('online',live?'● 服务器在线':'● 监控连接中断');$('online').classList.toggle('off',!live);val('refresh',`监控 RTT ${num(s.metrics_rtt_ms,0)} ms · 数据 ${num(s.metrics_age_s,1)}s 前`);
 val('phase',phaseNames[c.state]||c.state||'等待采集');val('sessionInfo',active?`${c.source_name||'输入源'} · ${num(c.width,0)} × ${num(c.height,0)} · ${c.codec==='raw_bgr'?'本机画面直传':(c.codec||'jpeg').toUpperCase()} · ${cfg.target_fps||30} FPS 输入/输出 · 30 Hz 模型时间轴`:'选择输入源，开始你的实时动捕');$('phaseDot').classList.toggle('on',c.state==='streaming');$('captureDot').classList.toggle('on',c.state==='streaming');$('serverDot').classList.toggle('on',live);$('motionDot').classList.toggle('on',r.connected);
 val('upFps',num(c.upload_fps??0));val('upRate',`${num(c.upload_mbps??0,2)} Mbps`);val('motionFps',num(r.motion_fps??0));val('udpFps',`UDP ${num(r.udp_fps??0)} Hz`);val('rxCount',`累计 ${num(r.rx,0)} 条`);val('workerMem',live&&device?num(device.used_mib/1024,2):'—');val('totalMem',`总容量 ${device?num(device.total_mib/1024,1):'—'} GiB · 含其他进程`);val('gpuUtil',`GPU ${live&&device?num(device.utilization_percent,0):'—'}%`);val('gpuAttribution',g.worker_used_mib===null?'容器 PID 与宿主机不同，进程显存暂不可归属；此处整卡显存包含其他进程。':'进程显存仅在 GPU PID 可准确匹配时显示。');
 val('encodeLabel',c.codec==='raw_bgr'?'画面打包（无编码）':'编码耗时');val('decodeLabel',n.codec==='raw_bgr'?'画面还原（无解码）':'服务器解码');$('codec').title=remote.deployment_mode==='local'?'本机自动直传；压缩设置仅用于远程连接。':'';
 val('latency',live&&remote.running?num(t.measured_latency_ms,0):'—');val('latencyTarget',`目标 ${num(t.target_latency_ms,0)} ms`);val('capFps',`${num(c.capture_fps??0)} FPS`);val('encode',`${num(c.encode_ms,2)} ms`);val('send',`${num(c.send_ms,2)} ms`);val('sentFrames',`${num(c.frames_sent??0,0)} 帧 · ${num((c.bytes_sent??0)/1048576,1)} MiB`);
 unitVal('samStride',num(cfg.sam_stride,0),'帧');unitVal('bodyLayers',num(cfg.body_decoder_layers,0),'层');unitVal('steps',num(cfg.ode_steps,0),'步');val('inputCodec',`${n.codec==='raw_bgr'?'本机直传':(n.codec||'—').toUpperCase()} / ${num(n.decode_ms,2)} ms`);val('ackRtt',`${num(c.ack_rtt_ms,0)} ms`);val('decodeMs',`${num(c.server_decode_ms,2)} ms`);val('hands',cfg.hand_mode==='off'?'关闭':cfg.hand_mode||'—');val('yoloSize',num(cfg.yolo_size,0));val('compile',`${remote.sam_compile?.status==='active'?'已启用':'—'} / ${remote.solver_compile?.enabled?'已启用':'—'}`);val('cache',`${num(remote.constant_cache?.hits,0)} 命中 / ${num(remote.constant_cache?.entries,0)} 项`);val('staleNote',!live?'数据已过期':remote.running?'实时采样':'上次推理 · 已停止');
 for(const [name,field] of [['yolo','yolox_ms_per_frame'],['sam','sam_ms_per_frame'],['flow','mmdit_ms_per_window']]){val(name+'Ms',`${num(t[field],2)} ms`)}
 val('accepted',`${num(n.accepted,0)} / ${num(n.dropped,0)}`);val('solved',`${num(t.windows_solved,0)} / ${num(t.underruns,0)}`);val('queue',`${num(remote.input_queue_capacity,0)} 帧 / ${num(n.last_frame_id,0)}`);val('serverFps',`${num(t.capture_fps)} / ${num(t.playout_fps)}`);
 val('receiverState',r.connected?'已连接':r.running?'正在重连':'未连接');$('startCapture').disabled=active||busy||!live||!!remote.running||!!remote.network_input?.active||(kind==='camera'&&!$('cameraIndex').value);$('stopCapture').disabled=!active;$('maxEdge').disabled=active||kind==='video';$('codec').disabled=active;$('cameraIndex').disabled=active;$('refreshCameras').disabled=active;$('quality').disabled=active||$('codec').value==='h264';$('bitrate').disabled=active||$('codec').value==='jpeg';$('startReceiver').disabled=r.running;$('stopReceiver').disabled=!r.running;$('udpPort').disabled=r.running;val('sourceBadge',active?(c.kind==='camera'?'CAMERA INPUT':'VIDEO INPUT'):'LOCAL SOURCE');
 const localDirect=remote.deployment_mode==='local';if(localDirect){$('codec').disabled=true;$('quality').disabled=true;$('bitrate').disabled=true;}for(const option of $('codec').options){option.dataset.originalLabel=option.dataset.originalLabel||option.textContent;option.textContent=localDirect&&option.selected?'本机直传（无编码）':option.dataset.originalLabel;}
 $('applyParameters').disabled=parameterBusy||!parameterLoaded||!live||active||!!remote.running||!!remote.network_input?.active||!!(remote.parameters&&parameterLoaded&&remote.parameters.revision!==parameterLoaded.revision);
 let observed=remote.running?`运行观测：身体 ${num(remote.runtime_config?.sam?.body_decoder_layers,0)} 层 · FlowHMR ${num(remote.runtime_config?.solver_observed_steps,0)} 步`:'当前未推理；保存值在下次开始时生效，可能重新预热。';
 if(remote.fast_sam?.loaded){const f=remote.fast_sam,o=f.optimizations||{},p=f.prompt_cache||{}; observed+=` · ${f.name} · ${f.backbone_dtype} · correctives ${f.correctives?'on':'off'} · crop/mask/pose ${o.crop_calls||0}/${o.mask_calls||0}/${o.pose_computations||0} · prompt hits ${(p.hits_2d||0)+(p.hits_3d||0)} · TensorRT off`; $('runtimeObserved').title=f.model_source||'';}
 val('runtimeObserved',observed);
 if(!active&&(remote.running||remote.network_input?.active))val('fileHint','上一轮推理正在清理，释放输入通道后即可重新开始。');
 const error=s.metrics_error||r.error||c.error||t.error;val('errorText',error?`状态提示：${error}`:'暂无错误 · 断线自动重连');$('errorText').classList.toggle('error',!!error);
 const eventsKey=JSON.stringify(s.events);if(eventsKey!==lastEventsKey){lastEventsKey=eventsKey;const events=$('events');events.replaceChildren();for(const event of s.events){const row=document.createElement('div'),at=document.createElement('span');at.className='time';at.textContent=event.at;row.append(at,document.createTextNode(event.message));events.prepend(row)}}

}
async function poll(){
 if(pollTimer!==null){clearTimeout(pollTimer);pollTimer=null;}
 if(pollBusy){pollAgain=true;return;}
 if(document.hidden)return;
 pollBusy=true;
 try{const snapshot=await api('/api/status');if(!document.hidden)render(snapshot)}
 catch(e){if(!document.hidden){val('online','● 本机控制台已断开');$('online').classList.add('off')}}
 finally{pollBusy=false;const delay=pollAgain?0:5000;pollAgain=false;pollTimer=document.hidden?null:setTimeout(poll,delay);}
}
document.addEventListener('visibilitychange',()=>{if(document.hidden){if(pollTimer!==null)clearTimeout(pollTimer);pollTimer=null;}else poll()});

function switchKind(next){kind=next;$('videoTab').classList.toggle('active',kind==='video');$('cameraTab').classList.toggle('active',kind==='camera');$('videoControls').hidden=kind!=='video';$('cameraControls').hidden=kind!=='camera';$('maxEdge').disabled=kind==='video'||!!lastSnapshot?.client?.thread_active;if(kind==='camera')refreshCameras()}
$('videoTab').addEventListener('click',()=>switchKind('video'));$('cameraTab').addEventListener('click',()=>switchKind('camera'));$('chooseVideo').addEventListener('click',()=>$('file').click());$('videoPath').addEventListener('input',()=>selectedVideo='');
$('file').addEventListener('change',async()=>{const file=$('file').files[0];if(!file)return;busy=true;$('startCapture').disabled=true;val('fileHint','正在导入本机临时缓存，不会整段上传到服务器…');try{const suffix='.'+file.name.split('.').pop().toLowerCase(),r=await fetch('/api/upload',{method:'POST',headers:{'X-UI-Key':key,'X-File-Suffix':suffix},body:file}),j=await r.json();if(!r.ok)throw Error(j.error);selectedVideo=j.source;$('videoPath').value=file.name;val('fileHint',`已就绪 · ${num(file.size/1048576,1)} MiB · 点击开始后自动预处理再推流`)}catch(e){toast(e.message);val('fileHint','导入失败，请重新选择。')}finally{busy=false}});
$('startCapture').addEventListener('click',async()=>{try{if(kind==='camera'&&!$('cameraIndex').value)throw Error('请先刷新并选择摄像头');await api('/api/capture/start',{kind,camera_name:kind==='camera'?$('cameraIndex').selectedOptions[0]?.dataset.deviceName:undefined,source:kind==='camera'?$('cameraIndex').value:selectedVideo||$('videoPath').value,max_edge:Number($('maxEdge').value),jpeg_quality:Number($('quality').value),codec:$('codec').value,bitrate_kbps:Number($('bitrate').value)})}catch(e){toast(e.message)}});
for(const [id,path,data] of [['stopCapture','/api/capture/stop',()=>({})],['startReceiver','/api/receiver/start',()=>({port:Number($('udpPort').value)})],['stopReceiver','/api/receiver/stop',()=>({})]])$(id).addEventListener('click',async()=>{try{await api(path,data())}catch(e){toast(e.message)}});
$('export').addEventListener('click',()=>{if(!lastSnapshot)return;const blob=new Blob([JSON.stringify({exported_at:new Date().toISOString(),snapshot:lastSnapshot,rate_samples:[],gpu_samples:[],charts_disabled:true},null,2)],{type:'application/json'}),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download='motion-link-diagnostics.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)});
$('codec').addEventListener('change',()=>{$('quality').disabled=$('codec').value==='h264';$('bitrate').disabled=$('codec').value==='jpeg'});
poll();

function fillParameterForm(values){for(const [field,id] of Object.entries(parameterFields))if(values[field]!==undefined)$(id).value=String(values[field])}
function syncParameters(data){if(!data?.values||typeof data.revision!=='number')return;if(!parameterLoaded||(!parameterDirty&&data.revision!==parameterLoaded.revision)){parameterLoaded=data;fillParameterForm(data.values)}val('parameterRevision',`版本 ${data.revision}`);if(!parameterBusy){const stale=parameterLoaded&&parameterLoaded.revision!==data.revision;val('parameterNotice',stale?'服务器参数已有更新；请重新读取后应用。':data.active?'正在推理：可编辑草稿，停止采集后再应用。':parameterDirty?'草稿已修改，点击应用后由服务器校验并保存。':'已读取服务器保存值；停止采集后可应用修改。')}}
for(const id of Object.values(parameterFields))$(id).addEventListener('change',()=>{parameterDirty=true;val('parameterNotice','草稿已修改；停止采集后点击应用参数。')});
$('defaultParameters').addEventListener('click',()=>{fillParameterForm(parameterLoaded?.defaults||{sam_stride:3,body_decoder_layers:4,ode_steps:4,yolo_size:416,hand_mode:'off',hand_decoder_layers:2});parameterDirty=true;val('parameterNotice','已填入默认草稿，尚未发送到服务器。')});
async function readParameters(){parameterBusy=true;try{const data=await api('/api/settings/read',{});parameterDirty=false;parameterLoaded=null;syncParameters(data);val('parameterNotice','已重新读取服务器保存值。')}catch(e){val('parameterNotice',e.message)}finally{parameterBusy=false}}
$('readParameters').addEventListener('click',readParameters);
$('applyParameters').addEventListener('click',async()=>{if(!parameterLoaded)return;parameterBusy=true;$('applyParameters').disabled=true;val('parameterNotice','正在校验、保存并回读服务器参数…');try{const values={};for(const [field,id] of Object.entries(parameterFields))values[field]=field==='hand_mode'?$(id).value:Number($(id).value);const result=await api('/api/settings/apply',{revision:parameterLoaded.revision,values});parameterLoaded=result;parameterDirty=false;fillParameterForm(result.values);val('parameterNotice',`已保存并回读版本 ${result.revision}；下次开始推理生效。`);toast('参数已由服务器保存；重新开始采集后生效。')}catch(e){val('parameterNotice',e.message);toast(e.message)}finally{parameterBusy=false}});
readParameters();

let cameraScanBusy=false;
async function refreshCameras(){
 if(cameraScanBusy||lastSnapshot?.client?.thread_active)return;
 cameraScanBusy=true;const selected=$('cameraIndex').value,selectedName=$('cameraIndex').selectedOptions[0]?.dataset.deviceName;$('refreshCameras').disabled=true;val('cameraHint','正在枚举摄像头，不会打开或上传画面…');
 try{
  const result=await api('/api/cameras');const devices=result.devices||[];$('cameraIndex').replaceChildren();
  for(const d of devices){const option=document.createElement('option');option.value=String(d.index);option.dataset.deviceName=d.name;option.textContent=d.name+'（设备 '+d.index+'）';$('cameraIndex').append(option)}
  if(!devices.length){const option=document.createElement('option');option.value='';option.textContent='未找到摄像头';$('cameraIndex').append(option)}
  else if(selectedName&&devices.some(d=>d.name===selectedName))$('cameraIndex').value=String(devices.find(d=>d.name===selectedName).index);
  else if(!selectedName&&devices.some(d=>String(d.index)===selected))$('cameraIndex').value=selected;
  else{const preferred=devices.find(d=>/droidcam/i.test(d.name))||devices[0];$('cameraIndex').value=String(preferred.index)}
  val('cameraHint',result.error||`找到 ${devices.length} 个设备；选好后点击开始上传。`);
 }catch(e){val('cameraHint',e.message)}finally{cameraScanBusy=false;$('refreshCameras').disabled=!!lastSnapshot?.client?.thread_active}
}
$('refreshCameras').addEventListener('click',refreshCameras);refreshCameras();

const diag=document.createElement('button');diag.textContent='导出诊断 ZIP';diag.style.cssText='position:fixed;right:20px;bottom:20px;z-index:1000';diag.onclick=async()=>{try{const r=await fetch('/api/diagnostics',{headers:{'X-UI-Key':key}});if(!r.ok)throw Error(r.status);const u=URL.createObjectURL(await r.blob()),a=document.createElement('a');a.href=u;a.download='FlowHMR-diagnostics.zip';a.click();setTimeout(()=>URL.revokeObjectURL(u),5000)}catch(e){toast('诊断导出失败：'+e.message)}};document.body.appendChild(diag);

for(const [label,values] of [['8GB低负载',{sam_stride:6,body_decoder_layers:1,ode_steps:1,yolo_size:416,hand_mode:'off',hand_decoder_layers:1}],['交接原始档',{sam_stride:4,body_decoder_layers:4,ode_steps:2,yolo_size:416,hand_mode:'fast',hand_decoder_layers:1}]]){const b=document.createElement('button');b.className='btn ghost';b.textContent=label;b.onclick=()=>{fillParameterForm(values);parameterDirty=true;val('parameterNotice','已填入'+label+'草稿；停止采集后点击应用参数。')};$('defaultParameters').parentNode.appendChild(b)}
