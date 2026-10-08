import type { ReactNode } from 'react'

// The overlay owns available height. Only the body scrolls; close remains reachable.
export default function DialogFrame({title,onClose,closeLabel,closeDisabled=false,className='',bodyClassName='',headerActions,footer,children}: {
  title:ReactNode;onClose:()=>void;closeLabel:string;closeDisabled?:boolean;className?:string;bodyClassName?:string;
  headerActions?:ReactNode;footer?:ReactNode;children:ReactNode;
}) {
  return <section className={`${className} dialog-frame`}>
    <header className="dialog-header"><h2 title={typeof title==='string'?title:undefined}>{title}</h2>
      <div className="dialog-header-actions">{headerActions}<button className="icon-button" type="button" disabled={closeDisabled} aria-label={closeLabel} onClick={onClose}>×</button></div>
    </header>
    <div className={`dialog-body ${bodyClassName}`} tabIndex={0}>{children}</div>
    {footer&&<footer className="dialog-footer">{footer}</footer>}
  </section>
}
