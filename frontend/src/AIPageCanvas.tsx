import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import type { AIAttachment, AIRegion } from './agentTypes'

type Rect = AIRegion['rect']
const whole: Rect = [0,0,1,1]
const bound = (n:number) => Math.max(0,Math.min(1,n))
export default function AIPageCanvas({page, focus, boxes, crop, onCrop, enlarged, onEnlarge, fitInside=false}: {
  page:AIAttachment; focus?:Rect; boxes:{rect:Rect; figure?:boolean; selected?:boolean}[];
  fitInside?:boolean; crop?:Rect; onCrop?:(rect:Rect)=>void; enlarged:boolean; onEnlarge:()=>void
}) {
  const host=useRef<HTMLDivElement>(null), image=useRef<HTMLImageElement>(null)
  const [size,setSize]=useState({w:1,h:1}),[zoom,setZoom]=useState(1)
  const [mode,setMode]=useState<'focus'|'page'>('focus'),[reset,setReset]=useState(0)
  const [redraw,setRedraw]=useState(false)
  const previous=useRef<{key:string;w:number;h:number;width:number;height:number;x:number;y:number}|null>(null)
  const anchor=useRef<{x:number;y:number}|null>(null)
  const drag=useRef<{x:number;y:number;left:number;top:number;rect?:Rect;handle?:string;point:[number,number]}|null>(null)
  useLayoutEffect(()=>{
    const measure=()=>{const node=host.current;if(node&&node.clientWidth>0&&node.clientHeight>0)setSize(old=>old.w===node.clientWidth&&old.h===node.clientHeight?old:{w:node.clientWidth,h:node.clientHeight})}
    measure();const observer=new ResizeObserver(measure);if(host.current)observer.observe(host.current)
    window.addEventListener('resize',measure);return()=>{observer.disconnect();window.removeEventListener('resize',measure)}
  },[])
  const signature=JSON.stringify(focus)
  useEffect(()=>{setMode('focus');setZoom(1);setReset(n=>n+1);setRedraw(false);drag.current=null},[page.id,signature,fitInside])
  const view=mode==='page'?whole:focus||whole,contain=mode==='page'||fitInside
  const horizontal=Math.max(1,size.w-24)/(page.width*(view[2]-view[0]))
  const scale=(contain?Math.min(horizontal,Math.max(1,size.h-24)/(page.height*(view[3]-view[1]))):horizontal)*zoom
  const width=Math.max(1,page.width*scale),height=Math.max(1,page.height*scale)
  const x=Math.max(12,(size.w-width)/2),y=Math.max(12,(size.h-height)/2)
  const key=JSON.stringify([page.id,signature,fitInside,reset,mode])
  useLayoutEffect(()=>{
    const node=host.current;if(!node||size.w<=1||size.h<=1)return
    const old=previous.current
    if(!old||old.key!==key){
      node.scrollLeft=x+width*(view[0]+view[2])/2-size.w/2
      node.scrollTop=contain?y+height*(view[1]+view[3])/2-size.h/2:y+height*view[1]-12
    }else if(old.width!==width||old.height!==height||old.w!==size.w||old.h!==size.h){
      const a=anchor.current?.x??bound((node.scrollLeft+old.w/2-old.x)/old.width),b=anchor.current?.y??bound((node.scrollTop+old.h/2-old.y)/old.height)
      node.scrollLeft=x+width*a-size.w/2;node.scrollTop=y+height*b-size.h/2
    }
    previous.current={key,w:size.w,h:size.h,width,height,x,y}
    anchor.current={x:bound((node.scrollLeft+size.w/2-x)/width),y:bound((node.scrollTop+size.h/2-y)/height)}
  },[key,width,height,x,y,size.w,size.h])
  useEffect(()=>{
    const node=host.current;if(!node)return
    const wheel=(event:WheelEvent)=>{
      if(event.ctrlKey)return
      event.preventDefault()
      const unit=event.deltaMode===1?16:event.deltaMode===2?node.clientHeight:1
      if(event.shiftKey)node.scrollLeft+=(event.deltaX||event.deltaY)*unit
      else {node.scrollTop+=event.deltaY*unit;node.scrollLeft+=event.deltaX*unit}
    }
    node.addEventListener('wheel',wheel,{passive:false});return()=>node.removeEventListener('wheel',wheel)
  },[])
  const point=(event:React.PointerEvent):[number,number]=>{const r=image.current!.getBoundingClientRect();return[bound((event.clientX-r.left)/r.width),bound((event.clientY-r.top)/r.height)]}
  const rectStyle=(r:Rect)=>({left:`${r[0]*100}%`,top:`${r[1]*100}%`,width:`${(r[2]-r[0])*100}%`,height:`${(r[3]-r[1])*100}%`})
  const fit=(next:'focus'|'page')=>{setMode(next);setZoom(1);setReset(n=>n+1)}
  return <div className="ai-page-viewer">
    <div className="ai-canvas-tools"><button onClick={()=>fit('focus')}>适应题目</button><button onClick={()=>fit('page')}>查看整页</button><button aria-label="缩小原图" onClick={()=>setZoom(z=>Math.max(.5,z/1.25))}>−</button><span>{Math.round(zoom*100)}%</span><button aria-label="放大原图" onClick={()=>setZoom(z=>Math.min(8,z*1.25))}>＋</button><button onClick={onEnlarge}>{enlarged?'恢复对照':'放大工作区'}</button>{onCrop&&<button aria-pressed={redraw} onClick={()=>setRedraw(v=>!v)}>重新框选</button>}</div>
    <div className={`ai-page-canvas ${redraw?'drawing':''}`} ref={host} aria-label="原材料画布" tabIndex={0} onScroll={()=>{
      const node=host.current,old=previous.current,r=image.current?.getBoundingClientRect()
      // Ignore scroll clamping caused by a new layout until its anchor is restored.
      if(node&&old&&r&&Math.abs(r.width-old.width)<.1&&node.clientWidth===old.w&&node.clientHeight===old.h)
        anchor.current={x:bound((node.scrollLeft+old.w/2-old.x)/old.width),y:bound((node.scrollTop+old.h/2-old.y)/old.height)}
    }}>
      <div className="ai-canvas-content" style={{width:Math.max(size.w,width+24),height:Math.max(size.h,height+24)}} onPointerDown={event=>{
        if(event.button!==0||!image.current)return
        // Content handlers leave native scrollbar interaction intact.
        event.currentTarget.setPointerCapture(event.pointerId)
        const handle=(event.target as HTMLElement).dataset.handle,node=host.current!
        drag.current={x:event.clientX,y:event.clientY,left:node.scrollLeft,top:node.scrollTop,rect:crop?[...crop]:undefined,handle:handle||(redraw&&onCrop?'draw':undefined),point:point(event)}
      }} onPointerMove={event=>{
        const d=drag.current;if(!d)return
        if(!d.handle){host.current!.scrollLeft=d.left+d.x-event.clientX;host.current!.scrollTop=d.top+d.y-event.clientY;return}
        const [a,b]=point(event);let r:Rect
        if(d.handle==='draw')r=[Math.min(a,d.point[0]),Math.min(b,d.point[1]),Math.max(a,d.point[0]),Math.max(b,d.point[1])]
        else {r=[...d.rect!];if(d.handle.includes('w'))r[0]=Math.min(a,r[2]-.005);if(d.handle.includes('e'))r[2]=Math.max(a,r[0]+.005);if(d.handle.includes('n'))r[1]=Math.min(b,r[3]-.005);if(d.handle.includes('s'))r[3]=Math.max(b,r[1]+.005)}
        if(r[2]-r[0]>=.005&&r[3]-r[1]>=.005)onCrop?.(r)
      }} onPointerUp={()=>{drag.current=null;setRedraw(false)}} onPointerCancel={()=>{drag.current=null}}>
        <div className="ai-canvas-page" style={{width,height,left:x,top:y}}><img ref={image} src={page.url} alt="核对原材料" draggable={false}/>
          {boxes.map((b,n)=><div key={n} className={`ai-material-box ${b.figure?'figure':''} ${b.selected?'selected':''}`} style={rectStyle(b.rect)}/>)}
          {crop&&<div className="ai-canvas-crop" style={rectStyle(crop)}>{['nw','ne','sw','se','n','s','w','e'].map(h=><button key={h} data-handle={h} className={`handle-${h}`} aria-label={`裁剪${h}边界`}/>)}</div>}
        </div>
      </div>
    </div>
  </div>
}
