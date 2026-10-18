import{$n as e,$t as t,A as n,An as r,C as i,Fn as a,Ht as o,In as s,J as c,L as l,R as u,Rn as d,Rt as f,Tn as p,Vt as m,X as h,Yn as g,Yt as _,Z as v,bn as y,cn as b,dn as x,et as S,gn as C,j as w,kn as T,ln as E,nt as D,ot as O,qn as k,rn as A,sn as j,vn as M,w as N,xn as P,zt as F}from"./vue-router-CtlYBEfb.js";import{n as I}from"./replaceable-6dRcqCPk.js";import{t as L}from"./use-merged-state-vBUfWV25.js";import{t as R}from"./format-length-BwSo_EUP.js";import{D as ee,F as z,K as B,Q as V,X as H,Y as U,Z as W,ct as G,f as K,h as q,lt as J,ot as Y,st as X}from"./index-1sxyyN4B.js";var Z=[`onMouseenter`,`onMouseleave`,`onMousedown`],Q={key:1,role:`none`},te=C({name:`NDrawerContent`,inheritAttrs:!1,props:{blockScroll:Boolean,show:{type:Boolean,default:void 0},displayDirective:{type:String,required:!0},placement:{type:String,required:!0},contentClass:String,contentStyle:[Object,String],nativeScrollbar:{type:Boolean,required:!0},scrollbarProps:Object,trapFocus:{type:Boolean,default:!0},autoFocus:{type:Boolean,default:!0},showMask:{type:[Boolean,String],required:!0},maxWidth:Number,maxHeight:Number,minWidth:Number,minHeight:Number,resizable:Boolean,onClickoutside:Function,onAfterLeave:Function,onAfterEnter:Function,onEsc:Function},setup(e){let n=k(!!e.show),i=k(null),o=y(J),c=0,l=``,u=null,d=k(!1),f=k(!1),m=j(()=>e.placement===`top`||e.placement===`bottom`),{mergedClsPrefixRef:h,mergedRtlRef:g}=D(e),_=N(`Drawer`,g,h),v=A,b=e=>{f.value=!0,c=m.value?e.clientY:e.clientX,l=document.body.style.cursor,document.body.style.cursor=m.value?`ns-resize`:`ew-resize`,document.body.addEventListener(`mousemove`,O),document.body.addEventListener(`mouseleave`,v),document.body.addEventListener(`mouseup`,A)},x=()=>{u!==null&&(window.clearTimeout(u),u=null),f.value?d.value=!0:u=window.setTimeout(()=>{d.value=!0},300)},S=()=>{u!==null&&(window.clearTimeout(u),u=null),d.value=!1},{doUpdateHeight:C,doUpdateWidth:w}=o,T=t=>{let{maxWidth:n}=e;if(n&&t>n)return n;let{minWidth:r}=e;return r&&t<r?r:t},E=t=>{let{maxHeight:n}=e;if(n&&t>n)return n;let{minHeight:r}=e;return r&&t<r?r:t};function O(t){if(f.value){if(m.value){let n=i.value?.offsetHeight||0,r=c-t.clientY;n+=e.placement===`bottom`?r:-r,n=E(n),C(n),c=t.clientY}else{let n=i.value?.offsetWidth||0,r=c-t.clientX;n+=e.placement===`right`?r:-r,n=T(n),w(n),c=t.clientX}}}function A(){f.value&&(c=0,f.value=!1,document.body.style.cursor=l,document.body.removeEventListener(`mousemove`,O),document.body.removeEventListener(`mouseup`,A),document.body.removeEventListener(`mouseleave`,v))}s(()=>{e.show&&(n.value=!0)}),a(()=>e.show,e=>{e||A()}),p(()=>{A()});let M=j(()=>{let{show:n}=e,r=[[t,n]];return e.showMask||r.push([V,e.onClickoutside,void 0,{capture:!0}]),r});function P(){n.value=!1,e.onAfterLeave?.()}return z(j(()=>e.blockScroll&&n.value)),r(G,i),r(Y,null),r(X,null),{bodyRef:i,rtlEnabled:_,mergedClsPrefix:o.mergedClsPrefixRef,isMounted:o.isMountedRef,mergedTheme:o.mergedThemeRef,displayed:n,transitionName:j(()=>({right:`slide-in-from-right-transition`,left:`slide-in-from-left-transition`,top:`slide-in-from-top-transition`,bottom:`slide-in-from-bottom-transition`})[e.placement]),handleAfterLeave:P,bodyDirectives:M,handleMousedownResizeTrigger:b,handleMouseenterResizeTrigger:x,handleMouseleaveResizeTrigger:S,isDragging:f,isHoverOnResizeTrigger:d}},render(){let{$slots:n,mergedClsPrefix:r}=this;return this.displayDirective===`show`||this.displayed||this.show?d((T(),x(`div`,Q,[(T(),E(U,{disabled:!this.showMask||!this.trapFocus,active:this.show,autoFocus:this.autoFocus,onEsc:this.onEsc},{default:()=>(T(),E(_,{name:this.transitionName,appear:this.isMounted,onAfterEnter:this.onAfterEnter,onAfterLeave:this.handleAfterLeave},{default:()=>d(M(`div`,P(this.$attrs,{role:`dialog`,ref:`bodyRef`,"aria-modal":`true`,class:[`${r}-drawer`,this.rtlEnabled&&`${r}-drawer--rtl`,`${r}-drawer--${this.placement}-placement`,this.isDragging&&`${r}-drawer--unselectable`,this.nativeScrollbar&&`${r}-drawer--native-scrollbar`]}),[this.resizable?(T(),x(`div`,{key:2,class:c([`${r}-drawer__resize-trigger`,(this.isDragging||this.isHoverOnResizeTrigger)&&`${r}-drawer__resize-trigger--hover`]),onMouseenter:this.handleMouseenterResizeTrigger,onMouseleave:this.handleMouseleaveResizeTrigger,onMousedown:this.handleMousedownResizeTrigger},null,42,Z)):null,this.nativeScrollbar?(T(),x(`div`,{key:3,class:c([`${r}-drawer-content-wrapper`,this.contentClass]),style:e(this.contentStyle),role:`none`},[v(()=>n.default?.())],6)):(T(),E(I,P({key:4},this.scrollbarProps,{contentStyle:this.contentStyle,contentClass:[`${r}-drawer-content-wrapper`,this.contentClass],theme:this.mergedTheme.peers.Scrollbar,themeOverrides:this.mergedTheme.peerOverrides.Scrollbar}),h(n),1040,[`contentStyle`,`contentClass`,`theme`,`themeOverrides`]))]),this.bodyDirectives)},1032,[`name`,`appear`,`onAfterEnter`,`onAfterLeave`]))},1032,[`disabled`,`active`,`autoFocus`,`onEsc`]))])),[[t,this.displayDirective===`if`||this.displayed||this.show]]):null}}),{cubicBezierEaseIn:ne,cubicBezierEaseOut:re}=S;function ie({duration:e=`0.3s`,leaveDuration:t=`0.2s`,name:n=`slide-in-from-bottom`}={}){return[f(`&.${n}-transition-leave-active`,{transition:`transform ${t} ${ne}`}),f(`&.${n}-transition-enter-active`,{transition:`transform ${e} ${re}`}),f(`&.${n}-transition-enter-to`,{transform:`translateY(0)`}),f(`&.${n}-transition-enter-from`,{transform:`translateY(100%)`}),f(`&.${n}-transition-leave-from`,{transform:`translateY(0)`}),f(`&.${n}-transition-leave-to`,{transform:`translateY(100%)`})]}var{cubicBezierEaseIn:ae,cubicBezierEaseOut:oe}=S;function se({duration:e=`0.3s`,leaveDuration:t=`0.2s`,name:n=`slide-in-from-left`}={}){return[f(`&.${n}-transition-leave-active`,{transition:`transform ${t} ${ae}`}),f(`&.${n}-transition-enter-active`,{transition:`transform ${e} ${oe}`}),f(`&.${n}-transition-enter-to`,{transform:`translateX(0)`}),f(`&.${n}-transition-enter-from`,{transform:`translateX(-100%)`}),f(`&.${n}-transition-leave-from`,{transform:`translateX(0)`}),f(`&.${n}-transition-leave-to`,{transform:`translateX(-100%)`})]}var{cubicBezierEaseIn:ce,cubicBezierEaseOut:le}=S;function ue({duration:e=`0.3s`,leaveDuration:t=`0.2s`,name:n=`slide-in-from-right`}={}){return[f(`&.${n}-transition-leave-active`,{transition:`transform ${t} ${ce}`}),f(`&.${n}-transition-enter-active`,{transition:`transform ${e} ${le}`}),f(`&.${n}-transition-enter-to`,{transform:`translateX(0)`}),f(`&.${n}-transition-enter-from`,{transform:`translateX(100%)`}),f(`&.${n}-transition-leave-from`,{transform:`translateX(0)`}),f(`&.${n}-transition-leave-to`,{transform:`translateX(100%)`})]}var{cubicBezierEaseIn:de,cubicBezierEaseOut:fe}=S;function pe({duration:e=`0.3s`,leaveDuration:t=`0.2s`,name:n=`slide-in-from-top`}={}){return[f(`&.${n}-transition-leave-active`,{transition:`transform ${t} ${de}`}),f(`&.${n}-transition-enter-active`,{transition:`transform ${e} ${fe}`}),f(`&.${n}-transition-enter-to`,{transform:`translateY(0)`}),f(`&.${n}-transition-enter-from`,{transform:`translateY(-100%)`}),f(`&.${n}-transition-leave-from`,{transform:`translateY(0)`}),f(`&.${n}-transition-leave-to`,{transform:`translateY(-100%)`})]}var $=f([F(`drawer`,`
 word-break: break-word;
 line-height: var(--n-line-height);
 position: absolute;
 pointer-events: all;
 box-shadow: var(--n-box-shadow);
 transition:
 background-color .3s var(--n-bezier),
 color .3s var(--n-bezier);
 background-color: var(--n-color);
 color: var(--n-text-color);
 box-sizing: border-box;
 `,[ue(),se(),pe(),ie(),o(`unselectable`,`
 user-select: none; 
 -webkit-user-select: none;
 `),o(`native-scrollbar`,[F(`drawer-content-wrapper`,`
 overflow: auto;
 height: 100%;
 `)]),m(`resize-trigger`,`
 position: absolute;
 background-color: #0000;
 transition: background-color .3s var(--n-bezier);
 `,[o(`hover`,`
 background-color: var(--n-resize-trigger-color-hover);
 `)]),F(`drawer-content-wrapper`,`
 box-sizing: border-box;
 `),F(`drawer-content`,`
 height: 100%;
 display: flex;
 flex-direction: column;
 `,[o(`native-scrollbar`,[F(`drawer-body-content-wrapper`,`
 height: 100%;
 overflow: auto;
 `)]),F(`drawer-body`,`
 flex: 1 0 0;
 overflow: hidden;
 `),F(`drawer-body-content-wrapper`,`
 box-sizing: border-box;
 padding: var(--n-body-padding);
 `),F(`drawer-header`,`
 font-weight: var(--n-title-font-weight);
 line-height: 1;
 font-size: var(--n-title-font-size);
 color: var(--n-title-text-color);
 padding: var(--n-header-padding);
 transition: border .3s var(--n-bezier);
 border-bottom: 1px solid var(--n-divider-color);
 border-bottom: var(--n-header-border-bottom);
 display: flex;
 justify-content: space-between;
 align-items: center;
 `,[m(`main`,`
 flex: 1;
 `),m(`close`,`
 margin-left: 6px;
 transition:
 background-color .3s var(--n-bezier),
 color .3s var(--n-bezier);
 `)]),F(`drawer-footer`,`
 display: flex;
 justify-content: flex-end;
 border-top: var(--n-footer-border-top);
 transition: border .3s var(--n-bezier);
 padding: var(--n-footer-padding);
 `)]),o(`right-placement`,`
 top: 0;
 bottom: 0;
 right: 0;
 border-top-left-radius: var(--n-border-radius);
 border-bottom-left-radius: var(--n-border-radius);
 `,[m(`resize-trigger`,`
 width: 3px;
 height: 100%;
 top: 0;
 left: 0;
 transform: translateX(-1.5px);
 cursor: ew-resize;
 `)]),o(`left-placement`,`
 top: 0;
 bottom: 0;
 left: 0;
 border-top-right-radius: var(--n-border-radius);
 border-bottom-right-radius: var(--n-border-radius);
 `,[m(`resize-trigger`,`
 width: 3px;
 height: 100%;
 top: 0;
 right: 0;
 transform: translateX(1.5px);
 cursor: ew-resize;
 `)]),o(`top-placement`,`
 top: 0;
 left: 0;
 right: 0;
 border-bottom-left-radius: var(--n-border-radius);
 border-bottom-right-radius: var(--n-border-radius);
 `,[m(`resize-trigger`,`
 width: 100%;
 height: 3px;
 bottom: 0;
 left: 0;
 transform: translateY(1.5px);
 cursor: ns-resize;
 `)]),o(`bottom-placement`,`
 left: 0;
 bottom: 0;
 right: 0;
 border-top-left-radius: var(--n-border-radius);
 border-top-right-radius: var(--n-border-radius);
 `,[m(`resize-trigger`,`
 width: 100%;
 height: 3px;
 top: 0;
 left: 0;
 transform: translateY(-1.5px);
 cursor: ns-resize;
 `)])]),f(`body`,[f(`>`,[F(`drawer-container`,`
 position: fixed;
 `)])]),F(`drawer-container`,`
 position: relative;
 position: absolute;
 left: 0;
 right: 0;
 top: 0;
 bottom: 0;
 pointer-events: none;
 `,[f(`> *`,`
 pointer-events: all;
 `)]),F(`drawer-mask`,`
 background-color: rgba(0, 0, 0, .3);
 position: absolute;
 left: 0;
 right: 0;
 top: 0;
 bottom: 0;
 `,[o(`invisible`,`
 background-color: rgba(0, 0, 0, 0)
 `),i({enterDuration:`0.2s`,leaveDuration:`0.2s`,enterCubicBezier:`var(--n-bezier-in)`,leaveCubicBezier:`var(--n-bezier-out)`})])]),me=[`onClick`],he={...l.props,show:Boolean,width:[Number,String],height:[Number,String],placement:{type:String,default:`right`},maskClosable:{type:Boolean,default:!0},showMask:{type:[Boolean,String],default:!0},to:[String,Object],displayDirective:{type:String,default:`if`},nativeScrollbar:{type:Boolean,default:!0},zIndex:Number,onMaskClick:Function,scrollbarProps:Object,contentClass:String,contentStyle:[Object,String],trapFocus:{type:Boolean,default:!0},onEsc:Function,autoFocus:{type:Boolean,default:!0},closeOnEsc:{type:Boolean,default:!0},blockScroll:{type:Boolean,default:!0},maxWidth:Number,maxHeight:Number,minWidth:Number,minHeight:Number,resizable:Boolean,defaultWidth:{type:[Number,String],default:251},defaultHeight:{type:[Number,String],default:251},onUpdateWidth:[Function,Array],onUpdateHeight:[Function,Array],"onUpdate:width":[Function,Array],"onUpdate:height":[Function,Array],"onUpdate:show":[Function,Array],onUpdateShow:[Function,Array],onAfterEnter:Function,onAfterLeave:Function,drawerStyle:[String,Object],drawerClass:String,target:null,onShow:Function,onHide:Function},ge=C({name:`Drawer`,inheritAttrs:!1,props:he,setup(e){let{mergedClsPrefixRef:t,namespaceRef:i,inlineThemeDisabled:a}=D(e),o=w(),s=l(`Drawer`,`-drawer`,$,K,e,t),c=k(e.defaultWidth),d=k(e.defaultHeight),f=L(g(e,`width`),c),p=L(g(e,`height`),d),m=j(()=>{let{placement:t}=e;return t===`top`||t===`bottom`?``:R(f.value)}),h=j(()=>{let{placement:t}=e;return t===`left`||t===`right`?``:R(p.value)}),_=t=>{let{onUpdateWidth:r,"onUpdate:width":i}=e;r&&n(r,t),i&&n(i,t),c.value=t},v=t=>{let{onUpdateHeight:r,"onUpdate:width":i}=e;r&&n(r,t),i&&n(i,t),d.value=t},y=j(()=>[{width:m.value,height:h.value},e.drawerStyle||``]);function b(t){let{onMaskClick:n,maskClosable:r}=e;r&&T(!1),n&&n(t)}function x(e){b(e)}let S=q();function C(t){e.onEsc?.(),e.show&&e.closeOnEsc&&ee(t)&&(S.value||T(!1))}function T(t){let{onHide:r,onUpdateShow:i,"onUpdate:show":a}=e;i&&n(i,t),a&&n(a,t),r&&!t&&n(r,t)}r(J,{isMountedRef:o,mergedThemeRef:s,mergedClsPrefixRef:t,doUpdateShow:T,doUpdateHeight:v,doUpdateWidth:_});let E=j(()=>{let{common:{cubicBezierEaseInOut:e,cubicBezierEaseIn:t,cubicBezierEaseOut:n},self:{color:r,textColor:i,boxShadow:a,lineHeight:o,headerPadding:c,footerPadding:l,borderRadius:u,bodyPadding:d,titleFontSize:f,titleTextColor:p,titleFontWeight:m,headerBorderBottom:h,footerBorderTop:g,closeIconColor:_,closeIconColorHover:v,closeIconColorPressed:y,closeColorHover:b,closeColorPressed:x,closeIconSize:S,closeSize:C,closeBorderRadius:w,resizableTriggerColorHover:T}}=s.value;return{"--n-line-height":o,"--n-color":r,"--n-border-radius":u,"--n-text-color":i,"--n-box-shadow":a,"--n-bezier":e,"--n-bezier-out":n,"--n-bezier-in":t,"--n-header-padding":c,"--n-body-padding":d,"--n-footer-padding":l,"--n-title-text-color":p,"--n-title-font-size":f,"--n-title-font-weight":m,"--n-header-border-bottom":h,"--n-footer-border-top":g,"--n-close-icon-color":_,"--n-close-icon-color-hover":v,"--n-close-icon-color-pressed":y,"--n-close-size":C,"--n-close-color-hover":b,"--n-close-color-pressed":x,"--n-close-icon-size":S,"--n-close-border-radius":w,"--n-resize-trigger-color-hover":T}}),O=a?u(`drawer`,void 0,E,e):void 0;return{mergedClsPrefix:t,namespace:i,mergedBodyStyle:y,handleOutsideClick:x,handleMaskClick:b,handleEsc:C,mergedTheme:s,cssVars:a?void 0:E,themeClass:O?.themeClass,onRender:O?.onRender,isMounted:o}},render(){let{mergedClsPrefix:t}=this;return T(),E(H,{to:this.to,show:this.show},{default:()=>(this.onRender?.(),d((T(),x(`div`,{class:c([`${t}-drawer-container`,this.namespace,this.themeClass]),style:e(this.cssVars),role:`none`},[this.showMask?(T(),E(_,{key:0,name:`fade-in-transition`,appear:this.isMounted},{default:()=>this.show?(T(),x(`div`,{key:1,"aria-hidden":!0,class:c([`${t}-drawer-mask`,this.showMask===`transparent`&&`${t}-drawer-mask--invisible`]),onClick:this.handleMaskClick},null,10,me)):null},1032,[`appear`])):v(()=>null),(T(),E(te,P(this.$attrs,{class:[this.drawerClass,this.$attrs.class],style:[this.mergedBodyStyle,this.$attrs.style],blockScroll:this.blockScroll,contentStyle:this.contentStyle,contentClass:this.contentClass,placement:this.placement,scrollbarProps:this.scrollbarProps,show:this.show,displayDirective:this.displayDirective,nativeScrollbar:this.nativeScrollbar,onAfterEnter:this.onAfterEnter,onAfterLeave:this.onAfterLeave,trapFocus:this.trapFocus,autoFocus:this.autoFocus,resizable:this.resizable,maxHeight:this.maxHeight,minHeight:this.minHeight,maxWidth:this.maxWidth,minWidth:this.minWidth,showMask:this.showMask,onEsc:this.handleEsc,onClickoutside:this.handleOutsideClick}),h(this.$slots),1040,[`class`,`style`,`blockScroll`,`contentStyle`,`contentClass`,`placement`,`scrollbarProps`,`show`,`displayDirective`,`nativeScrollbar`,`onAfterEnter`,`onAfterLeave`,`trapFocus`,`autoFocus`,`resizable`,`maxHeight`,`minHeight`,`maxWidth`,`minWidth`,`showMask`,`onEsc`,`onClickoutside`]))],6)),[[W,{zIndex:this.zIndex,enabled:this.show}]]))},1032,[`to`,`show`])}}),_e=C({name:`DrawerContent`,props:{title:String,headerClass:String,headerStyle:[Object,String],footerClass:String,footerStyle:[Object,String],bodyClass:String,bodyStyle:[Object,String],bodyContentClass:String,bodyContentStyle:[Object,String],nativeScrollbar:{type:Boolean,default:!0},scrollbarProps:Object,closable:Boolean},slots:Object,setup(){let e=y(J,null);e||O(`drawer-content`,"`n-drawer-content` must be placed inside `n-drawer`.");let{doUpdateShow:t}=e;function n(){t(!1)}return{handleCloseClick:n,mergedTheme:e.mergedThemeRef,mergedClsPrefix:e.mergedClsPrefixRef}},render(){let{title:t,mergedClsPrefix:n,nativeScrollbar:r,mergedTheme:i,bodyClass:a,bodyStyle:o,bodyContentClass:s,bodyContentStyle:l,headerClass:u,headerStyle:d,footerClass:f,footerStyle:p,scrollbarProps:m,closable:g,$slots:_}=this;return T(),x(`div`,{role:`none`,class:c([`${n}-drawer-content`,r&&`${n}-drawer-content--native-scrollbar`])},[_.header||t||g?(T(),x(`div`,{key:0,class:c([`${n}-drawer-header`,u]),style:e(d),role:`none`},[b(`div`,{class:c(`${n}-drawer-header__main`),role:`heading`,"aria-level":`1`},[_.header===void 0?(T(),x(A,{key:1},[v(()=>t)],64)):(T(),x(A,{key:0},[v(()=>_.header())],64))],2),v(()=>g&&(T(),E(B,{onClick:this.handleCloseClick,clsPrefix:n,class:c(`${n}-drawer-header__close`),absolute:!0},null,8,[`onClick`,`clsPrefix`,`class`])))],6)):v(()=>null),r?(T(),x(`div`,{key:2,class:c([`${n}-drawer-body`,a]),style:e(o),role:`none`},[b(`div`,{class:c([`${n}-drawer-body-content-wrapper`,s]),style:e(l),role:`none`},[v(()=>_.default?.())],6)],6)):(T(),E(I,P({key:3,themeOverrides:i.peerOverrides.Scrollbar,theme:i.peers.Scrollbar},m,{class:`${n}-drawer-body`,contentClass:[`${n}-drawer-body-content-wrapper`,s],contentStyle:l}),h(_),1040,[`themeOverrides`,`theme`,`class`,`contentClass`,`contentStyle`])),_.footer?(T(),x(`div`,{key:4,class:c([`${n}-drawer-footer`,f]),style:e(p),role:`none`},[v(()=>_.footer())],6)):v(()=>null)],2)}});export{ge as n,_e as t};