/* Narration is the single clock. Each clause owns one visual state. */
class AhaLiveStage {
 constructor(experience,media,stage){this.data=experience;this.media=media;this.stage=stage;this.canvas=stage.querySelector('canvas');this.caption=stage.parentElement.querySelector('.live-caption');this.ctx=this.canvas.getContext('2d');this.images=new Map();this.index=-1;this.lastTime=-1;this.autoZoom=true;this.zoomButton=stage.querySelector('.zoom-toggle');if(this.zoomButton)this.zoomButton.onclick=()=>{this.autoZoom=!this.autoZoom;this.zoomButton.textContent=this.autoZoom?'查看全图':'跟随讲解';this.lastTime=-1};new ResizeObserver(()=>this.resize()).observe(stage);this.resize();this.tick=this.tick.bind(this);requestAnimationFrame(this.tick)}
 // The stage is measured while the player may still be hidden, so a zero-sized read is
 // meaningless: writing it would blank every chapter until a ResizeObserver happens to
 // fire. Skip it and let tick() retry once the stage has a real size.
 resize(){const r=this.stage.getBoundingClientRect();if(r.width<1||r.height<1)return false;const dpr=Math.min(devicePixelRatio||1,2);this.canvas.width=Math.max(2,Math.round(r.width*dpr));this.canvas.height=Math.max(2,Math.round(r.height*dpr));this.sized=r.width+'x'+r.height;this.lastTime=-1;return true}
  activate(index){if(index===this.index)return;this.index=index;this.lastTime=-1;const visual=this.data.segments[index].visual;this.canvas.hidden=false;if(this.zoomButton)this.zoomButton.hidden=false;if(visual.kind==='figure'&&!this.images.has(visual.url)){const image=new Image();image.onload=()=>{this.lastTime=-1};image.src=visual.url;this.images.set(visual.url,image)}else if(visual.kind==='page'){for(const url of Object.values(visual.pages||{}))this.load(url)}}
 load(url){let image=this.images.get(url);if(!image){image=new Image();image.onload=()=>{this.lastTime=-1};image.src=url;this.images.set(url,image)}return image}
 tick(){// Re-measure every frame: cheap, and it removes the dependency on a ResizeObserver
 // notification arriving before the first paint.
 const r=this.stage.getBoundingClientRect();if(r.width>=1&&r.height>=1&&this.sized!==r.width+'x'+r.height)this.resize();if(this.data.segments.length){let index=this.data.segments.findIndex(s=>this.media.currentTime>=s.start&&this.media.currentTime<s.end);if(index<0)index=this.media.currentTime>0?this.data.segments.length-1:0;this.activate(index);const segment=this.data.segments[index],t=Math.max(0,this.media.currentTime-segment.start);if(Math.abs(t-this.lastTime)>.001){this.lastTime=t;const cues=segment.cues||[];let cueIndex=cues.findIndex(c=>t>=c.start&&t<c.end);if(cueIndex<0)cueIndex=t<=0?0:cues.length-1;const cue=cues[cueIndex];this.caption.textContent=cue?.text||'';this.renderState={segment:index,cue:cueIndex,text:cue?.text||'',kind:segment.visual.kind};if(segment.visual.kind==='page')this.drawPage(segment,t,cueIndex);else this.drawFigure(segment,t,cueIndex)}}requestAnimationFrame(this.tick)}
 region(r){return Array.isArray(r)&&r.length===4&&r.every(Number.isFinite)&&r[2]>0&&r[3]>0}
 crop(r){if(!this.autoZoom||!this.region(r)||r[2]*r[3]>.65)return [0,0,1,1];const w=Math.min(1,Math.max(.26,r[2]+.13)),h=Math.min(1,Math.max(.26,r[3]+.13));return [Math.max(0,Math.min(1-w,r[0]+r[2]/2-w/2)),Math.max(0,Math.min(1-h,r[1]+r[3]/2-h/2)),w,h]}
 /* Reading the paper itself. The highlight boxes come from the PDF's own text
    layer, so what is marked is exactly the sentence the narration is explaining --
    nothing here is positioned by a model. */
 rectBounds(rects){if(!rects?.length)return null;const x0=Math.min(...rects.map(r=>r[0])),y0=Math.min(...rects.map(r=>r[1])),x1=Math.max(...rects.map(r=>r[0]+r[2])),y1=Math.max(...rects.map(r=>r[1]+r[3]));return [x0,y0,x1-x0,y1-y0]}
 // A line of body text is wide and thin; frame it with enough page around it to
 // read the paragraph it sits in, or the viewer loses the place entirely.
 pageCrop(r){if(!this.autoZoom||!r)return [0,0,1,1];const w=Math.min(1,Math.max(.46,r[2]+.14)),h=Math.min(1,Math.max(.22,r[3]+.17));return [Math.max(0,Math.min(1-w,r[0]+r[2]/2-w/2)),Math.max(0,Math.min(1-h,r[1]+r[3]/2-h/2)),w,h]}
 drawPage(segment,t,cueIndex){const cues=segment.cues||[],cue=cues[cueIndex];if(!cue)return;
  const pages=segment.visual.pages||{},spot=cue.highlight||null;
  const url=pages[String(spot?.page??'')]||Object.values(pages)[0];if(!url)return;
  const image=this.load(url);if(!image?.complete||!image.naturalWidth)return;
  const ctx=this.ctx,W=this.canvas.width,H=this.canvas.height,dpr=Math.min(devicePixelRatio||1,2);
  ctx.setTransform(1,0,0,1,0,0);ctx.fillStyle='#ffffff';ctx.fillRect(0,0,W,H);
  const box=spot?this.rectBounds(spot.rects):null;
  // Only ease from the previous shot when it was on the same page; across a page
  // change the old coordinates mean nothing and the camera would sweep nonsense.
  const prior=cues[cueIndex-1]?.highlight,same=prior&&spot&&prior.page===spot.page;
  const target=this.pageCrop(box),before=same?this.pageCrop(this.rectBounds(prior.rects)):target;
  const elapsed=Math.max(0,t-cue.start);let a=Math.min(1,elapsed/.85);a=a*a*(3-2*a);
  const crop=target.map((v,i)=>before[i]+(v-before[i])*a);
  const margin=6*dpr,area={x:margin,y:margin,w:W-margin*2,h:H-margin*2};
  const sw=crop[2]*image.naturalWidth,sh=crop[3]*image.naturalHeight,fit=Math.min(area.w/sw,area.h/sh);
  const iw=sw*fit,ih=sh*fit,ix=area.x+(area.w-iw)/2,iy=area.y+(area.h-ih)/2;
  ctx.save();ctx.beginPath();ctx.rect(area.x,area.y,area.w,area.h);ctx.clip();
  ctx.fillStyle='#ffffff';ctx.fillRect(ix,iy,iw,ih);
  ctx.drawImage(image,crop[0]*image.naturalWidth,crop[1]*image.naturalHeight,sw,sh,ix,iy,iw,ih);
  if(spot?.rects?.length){
   const place=r=>[ix+(r[0]-crop[0])/crop[2]*iw,iy+(r[1]-crop[1])/crop[3]*ih,r[2]/crop[2]*iw,r[3]/crop[3]*ih];
   // Multiply keeps the words readable through the ink, the way a marker behaves.
   const wipe=Math.min(1,Math.max(0,elapsed/.55));ctx.globalCompositeOperation='multiply';
   for(const r of spot.rects){const [x,y,w,h]=place(r),pad=Math.max(1.5*dpr,h*.26);
    ctx.fillStyle='rgba(243,216,122,.62)';ctx.fillRect(x-pad*.6,y-pad,w*wipe+pad*1.2,h+pad*2)}
   // Key terms land after the marker has swept the whole line, so the sentence is
   // read first and the terms then lift out of it instead of competing with it.
   const lift=Math.min(1,Math.max(0,(elapsed-.5)/.5)),keys=lift>0?(spot.keys||[]):[];
   for(const k of keys)for(const r of k.rects||[]){const [x,y,w,h]=place(r),pad=Math.max(1.2*dpr,h*.2);
    ctx.fillStyle='rgba(240,178,64,.5)';ctx.fillRect(x-pad*.5,y-pad*.8,w*lift+pad,h+pad*1.6)}
   ctx.globalCompositeOperation='source-over';
   // A solid rule under the term. At 360px a second shade of yellow is
   // indistinguishable from the first; a dark line is still a line.
   for(const k of keys)for(const r of k.rects||[]){const [x,y,w,h]=place(r);
    ctx.fillStyle='rgba(166,88,24,.9)';
    ctx.fillRect(x,y+h+Math.max(1*dpr,h*.09),w*lift,Math.max(1.8*dpr,h*.1))}
   if(box){const [x,y,w,h]=place(box),pad=Math.max(2*dpr,h*.2);
    ctx.strokeStyle='rgba(176,134,47,.55)';ctx.lineWidth=1.6*dpr;ctx.setLineDash([5*dpr,4*dpr]);
    ctx.lineDashOffset=-t*9*dpr;ctx.strokeRect(x-pad*.6,y-pad,w+pad*1.2,h+pad*2);ctx.setLineDash([])}}
  ctx.restore();
  this.cameraState={crop,target,mode:crop[2]<1?'focus':'overview',cue:cueIndex};
  if((crop[2]<1||crop[3]<1)&&box)this.drawLocator(ctx,image,box,W,H,dpr)}
 drawFigure(segment,t,cueIndex){const image=this.images.get(segment.visual.url);if(!image?.complete||!image.naturalWidth)return;const ctx=this.ctx,W=this.canvas.width,H=this.canvas.height,dpr=Math.min(devicePixelRatio||1,2);ctx.setTransform(1,0,0,1,0,0);ctx.fillStyle='#ffffff';ctx.fillRect(0,0,W,H);const cues=segment.cues||[],cue=cues[cueIndex];if(!cue)return;const valid=this.region(cue.region),priorCue=cues[cueIndex-1];const target=this.crop(cue.region),before=this.crop(priorCue?.region),elapsed=Math.max(0,t-cue.start);let a=Math.min(1,elapsed/.9);a=a*a*(3-2*a);const crop=target.map((v,i)=>before[i]+(v-before[i])*a);const zoomed=target[2]<1||target[3]<1;this.cameraState={crop,target,mode:zoomed?'focus':'overview',cue:cueIndex};
 // The figure owns the whole stage; the locator is a small inset, not a column, and carries no label.
 const margin=6*dpr,area={x:margin,y:margin,w:W-margin*2,h:H-margin*2};const sw=crop[2]*image.naturalWidth,sh=crop[3]*image.naturalHeight,fit=Math.min(area.w/sw,area.h/sh),iw=sw*fit,ih=sh*fit,ix=area.x+(area.w-iw)/2,iy=area.y+(area.h-ih)/2;ctx.save();ctx.beginPath();ctx.rect(area.x,area.y,area.w,area.h);ctx.clip();ctx.drawImage(image,crop[0]*image.naturalWidth,crop[1]*image.naturalHeight,sw,sh,ix,iy,iw,ih);
 if(valid){const r=cue.region,targetPoint=[r[0]+r[2]/2,r[1]+r[3]/2];let prior=this.region(priorCue?.region)?[priorCue.region[0]+priorCue.region[2]/2,priorCue.region[1]+priorCue.region[3]/2]:targetPoint;const project=p=>[ix+(p[0]-crop[0])/crop[2]*iw,iy+(p[1]-crop[1])/crop[3]*ih];const point=when=>{let s=Math.min(1,Math.max(0,when/.65));s=s*s*(3-2*s);return project([prior[0]+(targetPoint[0]-prior[0])*s+Math.sin(when*1.9)*Math.min(r[2]*.045,.01)*s,prior[1]+(targetPoint[1]-prior[1])*s+Math.sin(when*2.7)*Math.min(r[3]*.04,.01)*s])};const p=point(elapsed);this.drawPointer(ctx,p,Array.from({length:7},(_,i)=>point(Math.max(0,elapsed-(7-i)*.04))),t,Math.max(24*dpr,Math.min(W/24,39*dpr)))}ctx.restore();
 if(zoomed&&valid)this.drawLocator(ctx,image,cue.region,W,H,dpr)}
 drawLocator(ctx,image,r,W,H,dpr){const pad=8*dpr,box=Math.min(W*.16,H*.28),fit=Math.min(box/image.naturalWidth,box/image.naturalHeight),w=image.naturalWidth*fit,h=image.naturalHeight*fit,x=W-18*dpr-pad-w,y=H-18*dpr-pad-h;ctx.save();ctx.fillStyle='#fffdf3';ctx.shadowColor='rgba(42,66,52,.20)';ctx.shadowBlur=11*dpr;ctx.shadowOffsetY=2*dpr;ctx.fillRect(x-pad,y-pad,w+pad*2,h+pad*2);ctx.shadowColor='transparent';ctx.globalAlpha=.85;ctx.drawImage(image,x,y,w,h);ctx.globalAlpha=1;ctx.fillStyle='rgba(139,166,118,.22)';ctx.strokeStyle='#7f9a6f';ctx.lineWidth=1.5*dpr;ctx.fillRect(x+r[0]*w,y+r[1]*h,r[2]*w,r[3]*h);ctx.strokeRect(x+r[0]*w,y+r[1]*h,r[2]*w,r[3]*h);ctx.restore()}
 drawPointer(ctx,[px,py],history,t,size){const radius=size*(.5+.04*Math.sin(t*4));ctx.fillStyle='rgba(176,207,190,.17)';ctx.beginPath();ctx.arc(px,py,radius,0,Math.PI*2);ctx.fill();ctx.strokeStyle='rgba(105,150,122,.62)';ctx.lineWidth=1.2;ctx.beginPath();ctx.arc(px,py,radius,t*.5,t*.5+Math.PI*1.58);ctx.stroke();history.forEach(([x,y],i)=>{ctx.fillStyle=`rgba(168,155,201,${(i+1)/18})`;ctx.beginPath();ctx.arc(x,y,size*(.025+.035*i/7),0,Math.PI*2);ctx.fill()});ctx.save();ctx.translate(px-size*.12,py-size*.1);ctx.scale(size,size);ctx.shadowColor='rgba(39,66,53,.23)';ctx.shadowBlur=5;ctx.shadowOffsetY=2;ctx.fillStyle='#fffdf2';ctx.strokeStyle='#416553';ctx.lineWidth=.055;ctx.lineJoin='round';ctx.beginPath();[[.12,.1],[.12,1.08],[.38,.86],[.58,1.26],[.77,1.16],[.57,.78],[.91,.77]].forEach(([x,y],i)=>i?ctx.lineTo(x,y):ctx.moveTo(x,y));ctx.closePath();ctx.fill();ctx.stroke();ctx.shadowColor='transparent';ctx.strokeStyle='#c7b9e2';ctx.lineWidth=.075;ctx.beginPath();ctx.moveTo(.25,.34);ctx.lineTo(.25,.67);ctx.stroke();ctx.restore()}
}
window.AhaLiveStage=AhaLiveStage;
