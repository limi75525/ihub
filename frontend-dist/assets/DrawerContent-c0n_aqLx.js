import{$t as e,B as t,F as n,Fn as r,Ht as i,Kt as a,Lt as o,M as s,Nt as c,P as l,R as u,St as d,T as f,Ut as p,W as m,Wt as h,Zt as g,_n as _,b as v,bn as y,dn as b,fn as x,jn as S,kn as C,kt as w,m as T,nn as E,on as D,tn as O,vn as ee,vt as k,w as A,x as j,xt as M,yt as N}from"./vue-router-DEBuQMrJ.js";import{d as P}from"./client-Cn9-q7d8.js";import{n as F}from"./replaceable-Cywrd9XW.js";import{t as I}from"./use-merged-state-C_DmUKj7.js";import{t as L}from"./format-length-BwSo_EUP.js";import{$ as te,I as R,O as z,Q as B,X as V,Z as H,ct as U,g as W,lt as G,p as K,q,st as J,ut as Y}from"./index-DEsgiSXB.js";var X=[`onMouseenter`,`onMouseleave`,`onMousedown`],Z={key:1,role:`none`},Q=g({name:`NDrawerContent`,inheritAttrs:!1,props:{blockScroll:Boolean,show:{type:Boolean,default:void 0},displayDirective:{type:String,required:!0},placement:{type:String,required:!0},contentClass:String,contentStyle:[Object,String],nativeScrollbar:{type:Boolean,required:!0},scrollbarProps:Object,trapFocus:{type:Boolean,default:!0},autoFocus:{type:Boolean,default:!0},showMask:{type:[Boolean,String],required:!0},maxWidth:Number,maxHeight:Number,minWidth:Number,minHeight:Number,resizable:Boolean,onClickoutside:Function,onAfterLeave:Function,onAfterEnter:Function,onEsc:Function},setup(e){let n=C(!!e.show),r=C(null),a=O(Y),o=0,s=``,l=null,u=C(!1),d=C(!1),f=i(()=>e.placement===`top`||e.placement===`bottom`),{mergedClsPrefixRef:p,mergedRtlRef:m}=t(e),h=T(`Drawer`,m,p),g=j,v=e=>{d.value=!0,o=f.value?e.clientY:e.clientX,s=document.body.style.cursor,document.body.style.cursor=f.value?`ns-resize`:`ew-resize`,document.body.addEventListener(`mousemove`,A),document.body.addEventListener(`mouseleave`,g),document.body.addEventListener(`mouseup`,j)},y=()=>{l!==null&&(window.clearTimeout(l),l=null),d.value?u.value=!0:l=window.setTimeout(()=>{u.value=!0},300)},b=()=>{l!==null&&(window.clearTimeout(l),l=null),u.value=!1},{doUpdateHeight:S,doUpdateWidth:w}=a,E=t=>{let{maxWidth:n}=e;if(n&&t>n)return n;let{minWidth:r}=e;return r&&t<r?r:t},k=t=>{let{maxHeight:n}=e;if(n&&t>n)return n;let{minHeight:r}=e;return r&&t<r?r:t};function A(t){if(d.value){if(f.value){let n=r.value?.offsetHeight||0,i=o-t.clientY;n+=e.placement===`bottom`?i:-i,n=k(n),S(n),o=t.clientY}else{let n=r.value?.offsetWidth||0,i=o-t.clientX;n+=e.placement===`right`?i:-i,n=E(n),w(n),o=t.clientX}}}function j(){d.value&&(o=0,d.value=!1,document.body.style.cursor=s,document.body.removeEventListener(`mousemove`,A),document.body.removeEventListener(`mouseup`,j),document.body.removeEventListener(`mouseleave`,g))}ee(()=>{e.show&&(n.value=!0)}),_(()=>e.show,e=>{e||j()}),D(()=>{j()});let M=i(()=>{let{show:t}=e,n=[[c,t]];return e.showMask||n.push([te,e.onClickoutside,void 0,{capture:!0}]),n});function N(){n.value=!1,e.onAfterLeave?.()}return R(i(()=>e.blockScroll&&n.value)),x(G,r),x(J,null),x(U,null),{bodyRef:r,rtlEnabled:h,mergedClsPrefix:a.mergedClsPrefixRef,isMounted:a.isMountedRef,mergedTheme:a.mergedThemeRef,displayed:n,transitionName:i(()=>({right:`slide-in-from-right-transition`,left:`slide-in-from-left-transition`,top:`slide-in-from-top-transition`,bottom:`slide-in-from-bottom-transition`})[e.placement]),handleAfterLeave:N,bodyDirectives:M,handleMousedownResizeTrigger:v,handleMouseenterResizeTrigger:y,handleMouseleaveResizeTrigger:b,isDragging:d,isHoverOnResizeTrigger:u}},render(){let{$slots:t,mergedClsPrefix:i}=this;return this.displayDirective===`show`||this.displayed||this.show?y((b(),a(`div`,Z,[(b(),h(V,{disabled:!this.showMask||!this.trapFocus,active:this.show,autoFocus:this.autoFocus,onEsc:this.onEsc},{default:()=>(b(),h(w,{name:this.transitionName,appear:this.isMounted,onAfterEnter:this.onAfterEnter,onAfterLeave:this.handleAfterLeave},{default:()=>y(e(`div`,E(this.$attrs,{role:`dialog`,ref:`bodyRef`,"aria-modal":`true`,class:[`${i}-drawer`,this.rtlEnabled&&`${i}-drawer--rtl`,`${i}-drawer--${this.placement}-placement`,this.isDragging&&`${i}-drawer--unselectable`,this.nativeScrollbar&&`${i}-drawer--native-scrollbar`]}),[this.resizable?(b(),a(`div`,{key:2,class:s([`${i}-drawer__resize-trigger`,(this.isDragging||this.isHoverOnResizeTrigger)&&`${i}-drawer__resize-trigger--hover`]),onMouseenter:this.handleMouseenterResizeTrigger,onMouseleave:this.handleMouseleaveResizeTrigger,onMousedown:this.handleMousedownResizeTrigger},null,42,X)):null,this.nativeScrollbar?(b(),a(`div`,{key:3,class:s([`${i}-drawer-content-wrapper`,this.contentClass]),style:r(this.contentStyle),role:`none`},[n(()=>t.default?.())],6)):(b(),h(F,E({key:4},this.scrollbarProps,{contentStyle:this.contentStyle,contentClass:[`${i}-drawer-content-wrapper`,this.contentClass],theme:this.mergedTheme.peers.Scrollbar,themeOverrides:this.mergedTheme.peerOverrides.Scrollbar}),l(t),1040,[`contentStyle`,`contentClass`,`theme`,`themeOverrides`]))]),this.bodyDirectives)},1032,[`name`,`appear`,`onAfterEnter`,`onAfterLeave`]))},1032,[`disabled`,`active`,`autoFocus`,`onEsc`]))])),[[c,this.displayDirective===`if`||this.displayed||this.show]]):null}}),{cubicBezierEaseIn:ne,cubicBezierEaseOut:re}=u;function ie({duration:e=`0.3s`,leaveDuration:t=`0.2s`,name:n=`slide-in-from-bottom`}={}){return[k(`&.${n}-transition-leave-active`,{transition:`transform ${t} ${ne}`}),k(`&.${n}-transition-enter-active`,{transition:`transform ${e} ${re}`}),k(`&.${n}-transition-enter-to`,{transform:`translateY(0)`}),k(`&.${n}-transition-enter-from`,{transform:`translateY(100%)`}),k(`&.${n}-transition-leave-from`,{transform:`translateY(0)`}),k(`&.${n}-transition-leave-to`,{transform:`translateY(100%)`})]}var{cubicBezierEaseIn:ae,cubicBezierEaseOut:oe}=u;function se({duration:e=`0.3s`,leaveDuration:t=`0.2s`,name:n=`slide-in-from-left`}={}){return[k(`&.${n}-transition-leave-active`,{transition:`transform ${t} ${ae}`}),k(`&.${n}-transition-enter-active`,{transition:`transform ${e} ${oe}`}),k(`&.${n}-transition-enter-to`,{transform:`translateX(0)`}),k(`&.${n}-transition-enter-from`,{transform:`translateX(-100%)`}),k(`&.${n}-transition-leave-from`,{transform:`translateX(0)`}),k(`&.${n}-transition-leave-to`,{transform:`translateX(-100%)`})]}var{cubicBezierEaseIn:ce,cubicBezierEaseOut:le}=u;function ue({duration:e=`0.3s`,leaveDuration:t=`0.2s`,name:n=`slide-in-from-right`}={}){return[k(`&.${n}-transition-leave-active`,{transition:`transform ${t} ${ce}`}),k(`&.${n}-transition-enter-active`,{transition:`transform ${e} ${le}`}),k(`&.${n}-transition-enter-to`,{transform:`translateX(0)`}),k(`&.${n}-transition-enter-from`,{transform:`translateX(100%)`}),k(`&.${n}-transition-leave-from`,{transform:`translateX(0)`}),k(`&.${n}-transition-leave-to`,{transform:`translateX(100%)`})]}var{cubicBezierEaseIn:de,cubicBezierEaseOut:fe}=u;function pe({duration:e=`0.3s`,leaveDuration:t=`0.2s`,name:n=`slide-in-from-top`}={}){return[k(`&.${n}-transition-leave-active`,{transition:`transform ${t} ${de}`}),k(`&.${n}-transition-enter-active`,{transition:`transform ${e} ${fe}`}),k(`&.${n}-transition-enter-to`,{transform:`translateY(0)`}),k(`&.${n}-transition-enter-from`,{transform:`translateY(-100%)`}),k(`&.${n}-transition-leave-from`,{transform:`translateY(0)`}),k(`&.${n}-transition-leave-to`,{transform:`translateY(-100%)`})]}var $=k([N(`drawer`,`
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
 `,[ue(),se(),pe(),ie(),d(`unselectable`,`
 user-select: none; 
 -webkit-user-select: none;
 `),d(`native-scrollbar`,[N(`drawer-content-wrapper`,`
 overflow: auto;
 height: 100%;
 `)]),M(`resize-trigger`,`
 position: absolute;
 background-color: #0000;
 transition: background-color .3s var(--n-bezier);
 `,[d(`hover`,`
 background-color: var(--n-resize-trigger-color-hover);
 `)]),N(`drawer-content-wrapper`,`
 box-sizing: border-box;
 `),N(`drawer-content`,`
 height: 100%;
 display: flex;
 flex-direction: column;
 `,[d(`native-scrollbar`,[N(`drawer-body-content-wrapper`,`
 height: 100%;
 overflow: auto;
 `)]),N(`drawer-body`,`
 flex: 1 0 0;
 overflow: hidden;
 `),N(`drawer-body-content-wrapper`,`
 box-sizing: border-box;
 padding: var(--n-body-padding);
 `),N(`drawer-header`,`
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
 `,[M(`main`,`
 flex: 1;
 `),M(`close`,`
 margin-left: 6px;
 transition:
 background-color .3s var(--n-bezier),
 color .3s var(--n-bezier);
 `)]),N(`drawer-footer`,`
 display: flex;
 justify-content: flex-end;
 border-top: var(--n-footer-border-top);
 transition: border .3s var(--n-bezier);
 padding: var(--n-footer-padding);
 `)]),d(`right-placement`,`
 top: 0;
 bottom: 0;
 right: 0;
 border-top-left-radius: var(--n-border-radius);
 border-bottom-left-radius: var(--n-border-radius);
 `,[M(`resize-trigger`,`
 width: 3px;
 height: 100%;
 top: 0;
 left: 0;
 transform: translateX(-1.5px);
 cursor: ew-resize;
 `)]),d(`left-placement`,`
 top: 0;
 bottom: 0;
 left: 0;
 border-top-right-radius: var(--n-border-radius);
 border-bottom-right-radius: var(--n-border-radius);
 `,[M(`resize-trigger`,`
 width: 3px;
 height: 100%;
 top: 0;
 right: 0;
 transform: translateX(1.5px);
 cursor: ew-resize;
 `)]),d(`top-placement`,`
 top: 0;
 left: 0;
 right: 0;
 border-bottom-left-radius: var(--n-border-radius);
 border-bottom-right-radius: var(--n-border-radius);
 `,[M(`resize-trigger`,`
 width: 100%;
 height: 3px;
 bottom: 0;
 left: 0;
 transform: translateY(1.5px);
 cursor: ns-resize;
 `)]),d(`bottom-placement`,`
 left: 0;
 bottom: 0;
 right: 0;
 border-top-left-radius: var(--n-border-radius);
 border-top-right-radius: var(--n-border-radius);
 `,[M(`resize-trigger`,`
 width: 100%;
 height: 3px;
 top: 0;
 left: 0;
 transform: translateY(-1.5px);
 cursor: ns-resize;
 `)])]),k(`body`,[k(`>`,[N(`drawer-container`,`
 position: fixed;
 `)])]),N(`drawer-container`,`
 position: relative;
 position: absolute;
 left: 0;
 right: 0;
 top: 0;
 bottom: 0;
 pointer-events: none;
 `,[k(`> *`,`
 pointer-events: all;
 `)]),N(`drawer-mask`,`
 background-color: rgba(0, 0, 0, .3);
 position: absolute;
 left: 0;
 right: 0;
 top: 0;
 bottom: 0;
 `,[d(`invisible`,`
 background-color: rgba(0, 0, 0, 0)
 `),P({enterDuration:`0.2s`,leaveDuration:`0.2s`,enterCubicBezier:`var(--n-bezier-in)`,leaveCubicBezier:`var(--n-bezier-out)`})])]),me=[`onClick`],he={...A.props,show:Boolean,width:[Number,String],height:[Number,String],placement:{type:String,default:`right`},maskClosable:{type:Boolean,default:!0},showMask:{type:[Boolean,String],default:!0},to:[String,Object],displayDirective:{type:String,default:`if`},nativeScrollbar:{type:Boolean,default:!0},zIndex:Number,onMaskClick:Function,scrollbarProps:Object,contentClass:String,contentStyle:[Object,String],trapFocus:{type:Boolean,default:!0},onEsc:Function,autoFocus:{type:Boolean,default:!0},closeOnEsc:{type:Boolean,default:!0},blockScroll:{type:Boolean,default:!0},maxWidth:Number,maxHeight:Number,minWidth:Number,minHeight:Number,resizable:Boolean,defaultWidth:{type:[Number,String],default:251},defaultHeight:{type:[Number,String],default:251},onUpdateWidth:[Function,Array],onUpdateHeight:[Function,Array],"onUpdate:width":[Function,Array],"onUpdate:height":[Function,Array],"onUpdate:show":[Function,Array],onUpdateShow:[Function,Array],onAfterEnter:Function,onAfterLeave:Function,drawerStyle:[String,Object],drawerClass:String,target:null,onShow:Function,onHide:Function},ge=g({name:`Drawer`,inheritAttrs:!1,props:he,setup(e){let{mergedClsPrefixRef:n,namespaceRef:r,inlineThemeDisabled:a}=t(e),o=j(),s=A(`Drawer`,`-drawer`,$,K,e,n),c=C(e.defaultWidth),l=C(e.defaultHeight),u=I(S(e,`width`),c),d=I(S(e,`height`),l),p=i(()=>{let{placement:t}=e;return t===`top`||t===`bottom`?``:L(u.value)}),m=i(()=>{let{placement:t}=e;return t===`left`||t===`right`?``:L(d.value)}),h=t=>{let{onUpdateWidth:n,"onUpdate:width":r}=e;n&&v(n,t),r&&v(r,t),c.value=t},g=t=>{let{onUpdateHeight:n,"onUpdate:width":r}=e;n&&v(n,t),r&&v(r,t),l.value=t},_=i(()=>[{width:p.value,height:m.value},e.drawerStyle||``]);function y(t){let{onMaskClick:n,maskClosable:r}=e;r&&E(!1),n&&n(t)}function b(e){y(e)}let w=W();function T(t){e.onEsc?.(),e.show&&e.closeOnEsc&&z(t)&&(w.value||E(!1))}function E(t){let{onHide:n,onUpdateShow:r,"onUpdate:show":i}=e;r&&v(r,t),i&&v(i,t),n&&!t&&v(n,t)}x(Y,{isMountedRef:o,mergedThemeRef:s,mergedClsPrefixRef:n,doUpdateShow:E,doUpdateHeight:g,doUpdateWidth:h});let D=i(()=>{let{common:{cubicBezierEaseInOut:e,cubicBezierEaseIn:t,cubicBezierEaseOut:n},self:{color:r,textColor:i,boxShadow:a,lineHeight:o,headerPadding:c,footerPadding:l,borderRadius:u,bodyPadding:d,titleFontSize:f,titleTextColor:p,titleFontWeight:m,headerBorderBottom:h,footerBorderTop:g,closeIconColor:_,closeIconColorHover:v,closeIconColorPressed:y,closeColorHover:b,closeColorPressed:x,closeIconSize:S,closeSize:C,closeBorderRadius:w,resizableTriggerColorHover:T}}=s.value;return{"--n-line-height":o,"--n-color":r,"--n-border-radius":u,"--n-text-color":i,"--n-box-shadow":a,"--n-bezier":e,"--n-bezier-out":n,"--n-bezier-in":t,"--n-header-padding":c,"--n-body-padding":d,"--n-footer-padding":l,"--n-title-text-color":p,"--n-title-font-size":f,"--n-title-font-weight":m,"--n-header-border-bottom":h,"--n-footer-border-top":g,"--n-close-icon-color":_,"--n-close-icon-color-hover":v,"--n-close-icon-color-pressed":y,"--n-close-size":C,"--n-close-color-hover":b,"--n-close-color-pressed":x,"--n-close-icon-size":S,"--n-close-border-radius":w,"--n-resize-trigger-color-hover":T}}),O=a?f(`drawer`,void 0,D,e):void 0;return{mergedClsPrefix:n,namespace:r,mergedBodyStyle:_,handleOutsideClick:b,handleMaskClick:y,handleEsc:T,mergedTheme:s,cssVars:a?void 0:D,themeClass:O?.themeClass,onRender:O?.onRender,isMounted:o}},render(){let{mergedClsPrefix:e}=this;return b(),h(H,{to:this.to,show:this.show},{default:()=>(this.onRender?.(),y((b(),a(`div`,{class:s([`${e}-drawer-container`,this.namespace,this.themeClass]),style:r(this.cssVars),role:`none`},[this.showMask?(b(),h(w,{key:0,name:`fade-in-transition`,appear:this.isMounted},{default:()=>this.show?(b(),a(`div`,{key:1,"aria-hidden":!0,class:s([`${e}-drawer-mask`,this.showMask===`transparent`&&`${e}-drawer-mask--invisible`]),onClick:this.handleMaskClick},null,10,me)):null},1032,[`appear`])):n(()=>null),(b(),h(Q,E(this.$attrs,{class:[this.drawerClass,this.$attrs.class],style:[this.mergedBodyStyle,this.$attrs.style],blockScroll:this.blockScroll,contentStyle:this.contentStyle,contentClass:this.contentClass,placement:this.placement,scrollbarProps:this.scrollbarProps,show:this.show,displayDirective:this.displayDirective,nativeScrollbar:this.nativeScrollbar,onAfterEnter:this.onAfterEnter,onAfterLeave:this.onAfterLeave,trapFocus:this.trapFocus,autoFocus:this.autoFocus,resizable:this.resizable,maxHeight:this.maxHeight,minHeight:this.minHeight,maxWidth:this.maxWidth,minWidth:this.minWidth,showMask:this.showMask,onEsc:this.handleEsc,onClickoutside:this.handleOutsideClick}),l(this.$slots),1040,[`class`,`style`,`blockScroll`,`contentStyle`,`contentClass`,`placement`,`scrollbarProps`,`show`,`displayDirective`,`nativeScrollbar`,`onAfterEnter`,`onAfterLeave`,`trapFocus`,`autoFocus`,`resizable`,`maxHeight`,`minHeight`,`maxWidth`,`minWidth`,`showMask`,`onEsc`,`onClickoutside`]))],6)),[[B,{zIndex:this.zIndex,enabled:this.show}]]))},1032,[`to`,`show`])}}),_e=g({name:`DrawerContent`,props:{title:String,headerClass:String,headerStyle:[Object,String],footerClass:String,footerStyle:[Object,String],bodyClass:String,bodyStyle:[Object,String],bodyContentClass:String,bodyContentStyle:[Object,String],nativeScrollbar:{type:Boolean,default:!0},scrollbarProps:Object,closable:Boolean},slots:Object,setup(){let e=O(Y,null);e||m(`drawer-content`,"`n-drawer-content` must be placed inside `n-drawer`.");let{doUpdateShow:t}=e;function n(){t(!1)}return{handleCloseClick:n,mergedTheme:e.mergedThemeRef,mergedClsPrefix:e.mergedClsPrefixRef}},render(){let{title:e,mergedClsPrefix:t,nativeScrollbar:i,mergedTheme:c,bodyClass:u,bodyStyle:d,bodyContentClass:f,bodyContentStyle:m,headerClass:g,headerStyle:_,footerClass:v,footerStyle:y,scrollbarProps:x,closable:S,$slots:C}=this;return b(),a(`div`,{role:`none`,class:s([`${t}-drawer-content`,i&&`${t}-drawer-content--native-scrollbar`])},[C.header||e||S?(b(),a(`div`,{key:0,class:s([`${t}-drawer-header`,g]),style:r(_),role:`none`},[p(`div`,{class:s(`${t}-drawer-header__main`),role:`heading`,"aria-level":`1`},[C.header===void 0?(b(),a(o,{key:1},[n(()=>e)],64)):(b(),a(o,{key:0},[n(()=>C.header())],64))],2),n(()=>S&&(b(),h(q,{onClick:this.handleCloseClick,clsPrefix:t,class:s(`${t}-drawer-header__close`),absolute:!0},null,8,[`onClick`,`clsPrefix`,`class`])))],6)):n(()=>null),i?(b(),a(`div`,{key:2,class:s([`${t}-drawer-body`,u]),style:r(d),role:`none`},[p(`div`,{class:s([`${t}-drawer-body-content-wrapper`,f]),style:r(m),role:`none`},[n(()=>C.default?.())],6)],6)):(b(),h(F,E({key:3,themeOverrides:c.peerOverrides.Scrollbar,theme:c.peers.Scrollbar},x,{class:`${t}-drawer-body`,contentClass:[`${t}-drawer-body-content-wrapper`,f],contentStyle:m}),l(C),1040,[`themeOverrides`,`theme`,`class`,`contentClass`,`contentStyle`])),C.footer?(b(),a(`div`,{key:4,class:s([`${t}-drawer-footer`,v]),style:r(y),role:`none`},[n(()=>C.footer())],6)):n(()=>null)],2)}});export{ge as n,_e as t};