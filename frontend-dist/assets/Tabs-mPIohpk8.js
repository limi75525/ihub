import{$t as e,At as t,B as n,Ct as r,F as i,Fn as a,Ht as o,Kt as s,L as c,Lt as l,M as u,Nt as d,P as f,St as p,T as m,U as h,Ut as g,Vt as _,W as v,Wt as y,Zt as b,_n as x,b as S,bn as C,dn as w,dt as T,fn as E,gt as D,j as O,jn as k,kn as A,ln as j,m as M,nn as N,rn as P,tn as F,vn as ee,vt as I,w as te,wt as L,xt as R,y as ne,yt as z}from"./vue-router-DEBuQMrJ.js";import{g as B,m as V}from"./client-Cn9-q7d8.js";import{f as re,i as H}from"./replaceable-Cywrd9XW.js";import{i as ie,n as U,r as W,t as G}from"./ChevronRight-DrLJWrVP.js";import{t as ae}from"./use-merged-state-C_DmUKj7.js";import{t as oe}from"./use-compitable-CZxTzUvH.js";import{D as se,N as ce,R as le,c as ue,it as de,q as fe}from"./index-B6X6aB_F.js";var pe=/\s/;function me(e){for(var t=e.length;t--&&pe.test(e.charAt(t)););return t}var he=/^\s+/;function ge(e){return e&&e.slice(0,me(e)+1).replace(he,``)}var _e=NaN,ve=/^[-+]0x[0-9a-f]+$/i,K=/^0b[01]+$/i,q=/^0o[0-7]+$/i,J=parseInt;function Y(e){if(typeof e==`number`)return e;if(re(e))return _e;if(T(e)){var t=typeof e.valueOf==`function`?e.valueOf():e;e=T(t)?t+``:t}if(typeof e!=`string`)return e===0?e:+e;e=ge(e);var n=K.test(e);return n||q.test(e)?J(e.slice(2),n?2:8):ve.test(e)?_e:+e}var X=function(){return D.Date.now()},ye=`Expected a function`,be=Math.max,Z=Math.min;function xe(e,t,n){var r,i,a,o,s,c,l=0,u=!1,d=!1,f=!0;if(typeof e!=`function`)throw TypeError(ye);t=Y(t)||0,T(n)&&(u=!!n.leading,d=`maxWait`in n,a=d?be(Y(n.maxWait)||0,t):a,f=`trailing`in n?!!n.trailing:f);function p(t){var n=r,a=i;return r=i=void 0,l=t,o=e.apply(a,n),o}function m(e){return l=e,s=setTimeout(_,t),u?p(e):o}function h(e){var n=e-c,r=e-l,i=t-n;return d?Z(i,a-r):i}function g(e){var n=e-c,r=e-l;return c===void 0||n>=t||n<0||d&&r>=a}function _(){var e=X();if(g(e))return v(e);s=setTimeout(_,h(e))}function v(e){return s=void 0,f&&r?p(e):(r=i=void 0,o)}function y(){s!==void 0&&clearTimeout(s),l=0,r=c=i=s=void 0}function b(){return s===void 0?o:v(X())}function x(){var e=X(),n=g(e);if(r=arguments,i=this,c=e,n){if(s===void 0)return m(c);if(d)return clearTimeout(s),s=setTimeout(_,t),p(c)}return s===void 0&&(s=setTimeout(_,t)),o}return x.cancel=y,x.flush=b,x}var Se=`Expected a function`;function Ce(e,t,n){var r=!0,i=!0;if(typeof e!=`function`)throw TypeError(Se);return T(n)&&(r=`leading`in n?!!n.leading:r,i=`trailing`in n?!!n.trailing:i),xe(e,t,{leading:r,maxWait:t,trailing:i})}var Q=U(`.v-x-scroll`,{overflow:`auto`,scrollbarWidth:`none`},[U(`&::-webkit-scrollbar`,{width:0,height:0})]),we=b({name:`XScroll`,props:{disabled:Boolean,onScroll:Function},setup(){let e=A(null);function t(e){e.currentTarget.offsetWidth<e.currentTarget.scrollWidth&&e.deltaY!==0&&(e.currentTarget.scrollLeft+=e.deltaY+e.deltaX,e.preventDefault())}let n=c();return Q.mount({id:`vueuc/x-scroll`,head:!0,anchorMetaName:W,ssr:n}),Object.assign({selfRef:e,handleWheel:t},{scrollTo(...t){var n;(n=e.value)==null||n.scrollTo(...t)}})},render(){return e(`div`,{ref:`selfRef`,onScroll:this.onScroll,onWheel:this.disabled?void 0:this.handleWheel,class:`v-x-scroll`},this.$slots)}}),$=b({name:`ChevronLeft`,render(){return(()=>{let e=O(`dfe229c2639b2082`);return e[0]||=g(`svg`,{viewBox:`0 0 16 16`,fill:`none`,xmlns:`http://www.w3.org/2000/svg`},[g(`path`,{d:`M10.3536 3.14645C10.5488 3.34171 10.5488 3.65829 10.3536 3.85355L6.20711 8L10.3536 12.1464C10.5488 12.3417 10.5488 12.6583 10.3536 12.8536C10.1583 13.0488 9.84171 13.0488 9.64645 12.8536L5.14645 8.35355C4.95118 8.15829 4.95118 7.84171 5.14645 7.64645L9.64645 3.14645C9.84171 2.95118 10.1583 2.95118 10.3536 3.14645Z`,fill:`currentColor`})],-1)})()}}),Te=b({name:`Add`,render(){return(()=>{let e=O(`b30130fbba5c5b23`);return e[0]||=g(`svg`,{width:`512`,height:`512`,viewBox:`0 0 512 512`,fill:`none`,xmlns:`http://www.w3.org/2000/svg`},[g(`path`,{d:`M256 112V400M400 256H112`,stroke:`currentColor`,"stroke-width":`32`,"stroke-linecap":`round`,"stroke-linejoin":`round`})],-1)})()}}),Ee=h(`n-tabs`),De={tab:[String,Number,Object,Function],name:{type:[String,Number],required:!0},disabled:Boolean,displayDirective:{type:String,default:`if`},closable:{type:Boolean,default:void 0},tabProps:Object,label:[String,Number,Object,Function]},Oe=b({__TAB_PANE__:!0,name:`TabPane`,alias:[`TabPanel`],props:De,slots:Object,setup(e){let t=F(Ee,null);return t||v(`tab-pane`,"`n-tab-pane` must be placed inside `n-tabs`."),{style:t.paneStyleRef,class:t.paneClassRef,mergedClsPrefix:t.mergedClsPrefixRef}},render(){return w(),s(`div`,{class:u([`${this.mergedClsPrefix}-tab-pane`,this.class]),style:a(this.style)},[i(()=>this.$slots.default?.())],6)}}),ke=[`data-name`,`data-disabled`],Ae={internalLeftPadded:Boolean,internalAddable:Boolean,internalCreatedByPane:Boolean,...se(De,[`displayDirective`])},je=b({__TAB__:!0,inheritAttrs:!1,name:`Tab`,props:Ae,setup(e){let{mergedClsPrefixRef:t,valueRef:n,typeRef:r,closableRef:i,tabStyleRef:a,addTabStyleRef:s,tabClassRef:c,addTabClassRef:l,tabChangeIdRef:u,onBeforeLeaveRef:d,triggerRef:f,handleAdd:p,activateTab:m,handleClose:h}=F(Ee);return{trigger:f,mergedClosable:o(()=>{if(e.internalAddable)return!1;let{closable:t}=e;return t===void 0?i.value:t}),style:a,addStyle:s,tabClass:c,addTabClass:l,clsPrefix:t,value:n,type:r,handleClose(t){t.stopPropagation(),!e.disabled&&h(e.name)},activateTab(){if(e.disabled)return;if(e.internalAddable){p();return}let{name:t}=e,r=++u.id;if(t!==n.value){let{value:i}=d;i?Promise.resolve(i(e.name,n.value)).then(e=>{e&&u.id===r&&m(t)}):m(t)}}}},render(){let{internalAddable:e,clsPrefix:t,name:n,disabled:r,label:a,tab:o,value:c,mergedClosable:d,trigger:f,$slots:{default:p}}=this,m=a??o;return w(),s(`div`,{class:u(`${t}-tabs-tab-wrapper`)},[this.internalLeftPadded?(w(),s(`div`,{key:0,class:u(`${t}-tabs-tab-pad`)},null,2)):i(()=>null),(w(),s(`div`,N({key:n,"data-name":n,"data-disabled":r?!0:void 0},N({class:[`${t}-tabs-tab`,c===n&&`${t}-tabs-tab--active`,r&&`${t}-tabs-tab--disabled`,d&&`${t}-tabs-tab--closable`,e&&`${t}-tabs-tab--addable`,e?this.addTabClass:this.tabClass],onClick:f===`click`?this.activateTab:void 0,onMouseenter:f===`hover`?this.activateTab:void 0,style:e?this.addStyle:this.style},this.internalCreatedByPane?this.tabProps||{}:this.$attrs)),[g(`span`,{class:u(`${t}-tabs-tab__label`)},[e?(w(),s(l,{key:0},[g(`div`,{class:u(`${t}-tabs-tab__height-placeholder`)},`\xA0`,2),(w(),y(V,{clsPrefix:t},{default:()=>(w(),y(Te))},1032,[`clsPrefix`]))],64)):(w(),s(l,{key:1},[p?(w(),s(l,{key:0},[i(()=>p())],64)):(w(),s(l,{key:1},[typeof m==`object`?(w(),s(l,{key:0},[i(()=>m)],64)):(w(),s(l,{key:1},[i(()=>le(m??n))],64))],64))],64))],2),d&&this.type===`card`?(w(),y(fe,{key:0,clsPrefix:t,class:u(`${t}-tabs-tab__close`),onClick:this.handleClose,disabled:r},null,8,[`clsPrefix`,`class`,`onClick`,`disabled`])):i(()=>null)],16,ke))],2)}}),Me=z(`tabs`,`
 box-sizing: border-box;
 width: 100%;
 display: flex;
 flex-direction: column;
 transition:
 background-color .3s var(--n-bezier),
 border-color .3s var(--n-bezier);
`,[I(`&.transition-disabled`,[z(`tabs-tab`,`
 transition: none !important;
 `),z(`tabs-nav-scroll-content`,`
 transition: none !important;
 `),z(`tabs-tab-pad`,`
 transition: none !important;
 `)]),p(`segment-type`,[z(`tabs-rail`,[I(`&.transition-disabled`,[z(`tabs-capsule`,`
 transition: none;
 `)])])]),p(`top`,[z(`tab-pane`,`
 padding: var(--n-pane-padding-top) var(--n-pane-padding-right) var(--n-pane-padding-bottom) var(--n-pane-padding-left);
 `)]),p(`left`,[z(`tab-pane`,`
 padding: var(--n-pane-padding-right) var(--n-pane-padding-bottom) var(--n-pane-padding-left) var(--n-pane-padding-top);
 `)]),p(`left, right`,`
 flex-direction: row;
 `,[z(`tabs-bar`,`
 width: 2px;
 right: 0;
 transition:
 top .2s var(--n-bezier),
 max-height .2s var(--n-bezier),
 background-color .3s var(--n-bezier);
 `),z(`tabs-tab`,`
 padding: var(--n-tab-padding-vertical); 
 `)]),p(`right`,`
 flex-direction: row-reverse;
 `,[z(`tab-pane`,`
 padding: var(--n-pane-padding-left) var(--n-pane-padding-top) var(--n-pane-padding-right) var(--n-pane-padding-bottom);
 `),z(`tabs-bar`,`
 left: 0;
 `)]),p(`bottom`,`
 flex-direction: column-reverse;
 justify-content: flex-end;
 `,[z(`tab-pane`,`
 padding: var(--n-pane-padding-bottom) var(--n-pane-padding-right) var(--n-pane-padding-top) var(--n-pane-padding-left);
 `),z(`tabs-bar`,`
 top: 0;
 `)]),z(`tabs-rail`,`
 position: relative;
 padding: 3px;
 border-radius: var(--n-tab-border-radius);
 width: 100%;
 background-color: var(--n-color-segment);
 transition: background-color .3s var(--n-bezier);
 display: flex;
 align-items: center;
 `,[z(`tabs-capsule`,`
 border-radius: var(--n-tab-border-radius);
 position: absolute;
 left: 0;
 top: 0;
 pointer-events: none;
 background-color: var(--n-tab-color-segment);
 box-shadow: 0 1px 3px 0 rgba(0, 0, 0, .08);
 transition: transform 0.3s var(--n-bezier);
 `),z(`tabs-tab-wrapper`,`
 flex-basis: 0;
 flex-grow: 1;
 display: flex;
 align-items: center;
 justify-content: center;
 `,[z(`tabs-tab`,`
 overflow: hidden;
 border-radius: var(--n-tab-border-radius);
 width: 100%;
 display: flex;
 align-items: center;
 justify-content: center;
 `,[p(`active`,`
 font-weight: var(--n-font-weight-strong);
 color: var(--n-tab-text-color-active);
 `),I(`&:hover`,`
 color: var(--n-tab-text-color-hover);
 `)])])]),p(`flex`,[z(`tabs-nav`,`
 width: 100%;
 position: relative;
 `,[z(`tabs-wrapper`,`
 width: 100%;
 `,[z(`tabs-tab`,`
 margin-right: 0;
 `)])])]),z(`tabs-nav`,`
 box-sizing: border-box;
 line-height: 1.5;
 display: flex;
 transition: border-color .3s var(--n-bezier);
 `,[R(`prefix, suffix`,`
 display: flex;
 align-items: center;
 `),R(`prefix`,`padding-right: 16px;`),R(`suffix`,`padding-left: 16px;`)]),p(`top, bottom`,[I(`>`,[z(`tabs-nav`,[z(`tabs-nav-scroll-wrapper`,[I(`&::before`,`
 top: 0;
 bottom: 0;
 left: 0;
 width: 20px;
 `),I(`&::after`,`
 top: 0;
 bottom: 0;
 right: 0;
 width: 20px;
 `),p(`shadow-start`,[I(`&::before`,`
 box-shadow: inset 10px 0 8px -8px rgba(0, 0, 0, .12);
 `)]),p(`shadow-end`,[I(`&::after`,`
 box-shadow: inset -10px 0 8px -8px rgba(0, 0, 0, .12);
 `)])])])])]),p(`left, right`,[z(`tabs-nav-scroll-content`,`
 flex-direction: column;
 `),I(`>`,[z(`tabs-nav`,[z(`tabs-nav-scroll-wrapper`,[I(`&::before`,`
 top: 0;
 left: 0;
 right: 0;
 height: 20px;
 `),I(`&::after`,`
 bottom: 0;
 left: 0;
 right: 0;
 height: 20px;
 `),p(`shadow-start`,[I(`&::before`,`
 box-shadow: inset 0 10px 8px -8px rgba(0, 0, 0, .12);
 `)]),p(`shadow-end`,[I(`&::after`,`
 box-shadow: inset 0 -10px 8px -8px rgba(0, 0, 0, .12);
 `)])])])])]),z(`tabs-nav-scroll-wrapper`,`
 flex: 1;
 position: relative;
 overflow: hidden;
 `,[z(`tabs-nav-y-scroll`,`
 height: 100%;
 width: 100%;
 overflow-y: auto; 
 scrollbar-width: none;
 `,[I(`&::-webkit-scrollbar, &::-webkit-scrollbar-track-piece, &::-webkit-scrollbar-thumb`,`
 width: 0;
 height: 0;
 display: none;
 `)]),I(`&::before, &::after`,`
 transition: box-shadow .3s var(--n-bezier);
 pointer-events: none;
 content: "";
 position: absolute;
 z-index: 1;
 `),I(`&.transition-disabled`,[I(`&::before, &::after`,`
 transition: none;
 `)])]),z(`tabs-nav-scroll-content`,`
 display: flex;
 position: relative;
 min-width: 100%;
 min-height: 100%;
 width: fit-content;
 box-sizing: border-box;
 `),z(`tabs-wrapper`,`
 display: inline-flex;
 flex-wrap: nowrap;
 position: relative;
 `),z(`tabs-tab-wrapper`,`
 display: flex;
 flex-wrap: nowrap;
 flex-shrink: 0;
 flex-grow: 0;
 `),z(`tabs-tab`,`
 cursor: pointer;
 white-space: nowrap;
 flex-wrap: nowrap;
 display: inline-flex;
 align-items: center;
 color: var(--n-tab-text-color);
 font-size: var(--n-tab-font-size);
 background-clip: padding-box;
 padding: var(--n-tab-padding);
 transition:
 box-shadow .3s var(--n-bezier),
 color .3s var(--n-bezier),
 background-color .3s var(--n-bezier),
 border-color .3s var(--n-bezier);
 `,[p(`disabled`,{cursor:`not-allowed`}),R(`close`,`
 margin-inline-start: 6px;
 transition:
 background-color .3s var(--n-bezier),
 color .3s var(--n-bezier);
 `),R(`label`,`
 display: flex;
 align-items: center;
 z-index: 1;
 `)]),z(`tabs-bar`,`
 position: absolute;
 bottom: 0;
 height: 2px;
 border-radius: 1px;
 background-color: var(--n-bar-color);
 transition:
 left .2s var(--n-bezier),
 max-width .2s var(--n-bezier),
 opacity .3s var(--n-bezier),
 background-color .3s var(--n-bezier);
 `,[I(`&.transition-disabled`,`
 transition: none;
 `),p(`disabled`,`
 background-color: var(--n-tab-text-color-disabled)
 `)]),z(`tabs-pane-wrapper`,`
 position: relative;
 overflow: hidden;
 transition: max-height .2s var(--n-bezier);
 `),z(`tab-pane`,`
 color: var(--n-pane-text-color);
 width: 100%;
 transition:
 color .3s var(--n-bezier),
 background-color .3s var(--n-bezier),
 opacity .2s var(--n-bezier);
 left: 0;
 right: 0;
 top: 0;
 `,[I(`&.next-transition-leave-active, &.prev-transition-leave-active, &.next-transition-enter-active, &.prev-transition-enter-active`,`
 transition:
 color .3s var(--n-bezier),
 background-color .3s var(--n-bezier),
 transform .2s var(--n-bezier),
 opacity .2s var(--n-bezier);
 `),I(`&.next-transition-leave-active, &.prev-transition-leave-active`,`
 position: absolute;
 `),I(`&.next-transition-enter-from, &.prev-transition-leave-to`,`
 transform: translateX(32px);
 opacity: 0;
 `),I(`&.next-transition-leave-to, &.prev-transition-enter-from`,`
 transform: translateX(-32px);
 opacity: 0;
 `),I(`&.next-transition-leave-from, &.next-transition-enter-to, &.prev-transition-leave-from, &.prev-transition-enter-to`,`
 transform: translateX(0);
 opacity: 1;
 `)]),z(`tabs-tab-pad`,`
 box-sizing: border-box;
 width: var(--n-tab-gap);
 flex-grow: 0;
 flex-shrink: 0;
 `),p(`line-type, bar-type`,[z(`tabs-tab`,`
 font-weight: var(--n-tab-font-weight);
 box-sizing: border-box;
 vertical-align: bottom;
 `,[I(`&:hover`,{color:`var(--n-tab-text-color-hover)`}),p(`active`,`
 color: var(--n-tab-text-color-active);
 font-weight: var(--n-tab-font-weight-active);
 `),p(`disabled`,{color:`var(--n-tab-text-color-disabled)`})])]),z(`tabs-nav`,[R(`prefix, suffix`,`
 border-color: var(--n-tab-border-color);
 `),z(`tabs-nav-scroll-content`,`
 border-color: var(--n-tab-border-color);
 `),p(`line-type`,[p(`top`,[R(`prefix, suffix`,`
 border-bottom: 1px solid var(--n-tab-border-color);
 `),z(`tabs-nav-scroll-content`,`
 border-bottom: 1px solid var(--n-tab-border-color);
 `),z(`tabs-bar`,`
 bottom: -1px;
 `)]),p(`left`,[R(`prefix, suffix`,`
 border-right: 1px solid var(--n-tab-border-color);
 `),z(`tabs-nav-scroll-content`,`
 border-right: 1px solid var(--n-tab-border-color);
 `),z(`tabs-bar`,`
 right: -1px;
 `)]),p(`right`,[R(`prefix, suffix`,`
 border-left: 1px solid var(--n-tab-border-color);
 `),z(`tabs-nav-scroll-content`,`
 border-left: 1px solid var(--n-tab-border-color);
 `),z(`tabs-bar`,`
 left: -1px;
 `)]),p(`bottom`,[R(`prefix, suffix`,`
 border-top: 1px solid var(--n-tab-border-color);
 `),z(`tabs-nav-scroll-content`,`
 border-top: 1px solid var(--n-tab-border-color);
 `),z(`tabs-bar`,`
 top: -1px;
 `)]),R(`prefix, suffix`,`
 transition: border-color .3s var(--n-bezier);
 `),z(`tabs-nav-scroll-content`,`
 transition: border-color .3s var(--n-bezier);
 `),z(`tabs-bar`,`
 border-radius: 0;
 `)]),p(`card-type`,[R(`prefix, suffix`,`
 transition: border-color .3s var(--n-bezier);
 `),z(`tabs-pad`,`
 flex-grow: 1;
 transition: border-color .3s var(--n-bezier);
 `),z(`tabs-tab-pad`,`
 transition: border-color .3s var(--n-bezier);
 `),z(`tabs-tab`,`
 font-weight: var(--n-tab-font-weight);
 border: 1px solid var(--n-tab-border-color);
 background-color: var(--n-tab-color);
 box-sizing: border-box;
 position: relative;
 vertical-align: bottom;
 display: flex;
 justify-content: space-between;
 font-size: var(--n-tab-font-size);
 color: var(--n-tab-text-color);
 `,[p(`addable`,`
 padding-left: 8px;
 padding-right: 8px;
 font-size: 16px;
 justify-content: center;
 `,[R(`height-placeholder`,`
 width: 0;
 font-size: var(--n-tab-font-size);
 `),r(`disabled`,[I(`&:hover`,`
 color: var(--n-tab-text-color-hover);
 `)])]),p(`closable`,`padding-inline-end: 8px;`),p(`active`,`
 background-color: #0000;
 font-weight: var(--n-tab-font-weight-active);
 color: var(--n-tab-text-color-active);
 `),p(`disabled`,`color: var(--n-tab-text-color-disabled);`)])]),p(`left, right`,`
 flex-direction: column; 
 `,[R(`prefix, suffix`,`
 padding: var(--n-tab-padding-vertical);
 `),z(`tabs-wrapper`,`
 flex-direction: column;
 `),z(`tabs-tab-wrapper`,`
 flex-direction: column;
 `,[z(`tabs-tab-pad`,`
 height: var(--n-tab-gap-vertical);
 width: 100%;
 `)])]),p(`top`,[p(`card-type`,[z(`tabs-scroll-padding`,`border-bottom: 1px solid var(--n-tab-border-color);`),R(`prefix, suffix`,`
 border-bottom: 1px solid var(--n-tab-border-color);
 `),z(`tabs-tab`,`
 border-top-left-radius: var(--n-tab-border-radius);
 border-top-right-radius: var(--n-tab-border-radius);
 `,[p(`active`,`
 border-bottom: 1px solid #0000;
 `)]),z(`tabs-tab-pad`,`
 border-bottom: 1px solid var(--n-tab-border-color);
 `),z(`tabs-pad`,`
 border-bottom: 1px solid var(--n-tab-border-color);
 `)])]),p(`left`,[p(`card-type`,[z(`tabs-scroll-padding`,`border-right: 1px solid var(--n-tab-border-color);`),R(`prefix, suffix`,`
 border-right: 1px solid var(--n-tab-border-color);
 `),z(`tabs-tab`,`
 border-top-left-radius: var(--n-tab-border-radius);
 border-bottom-left-radius: var(--n-tab-border-radius);
 `,[p(`active`,`
 border-right: 1px solid #0000;
 `)]),z(`tabs-tab-pad`,`
 border-right: 1px solid var(--n-tab-border-color);
 `),z(`tabs-pad`,`
 border-right: 1px solid var(--n-tab-border-color);
 `)])]),p(`right`,[p(`card-type`,[z(`tabs-scroll-padding`,`border-left: 1px solid var(--n-tab-border-color);`),R(`prefix, suffix`,`
 border-left: 1px solid var(--n-tab-border-color);
 `),z(`tabs-tab`,`
 border-top-right-radius: var(--n-tab-border-radius);
 border-bottom-right-radius: var(--n-tab-border-radius);
 `,[p(`active`,`
 border-left: 1px solid #0000;
 `)]),z(`tabs-tab-pad`,`
 border-left: 1px solid var(--n-tab-border-color);
 `),z(`tabs-pad`,`
 border-left: 1px solid var(--n-tab-border-color);
 `)])]),p(`bottom`,[p(`card-type`,[z(`tabs-scroll-padding`,`border-top: 1px solid var(--n-tab-border-color);`),R(`prefix, suffix`,`
 border-top: 1px solid var(--n-tab-border-color);
 `),z(`tabs-tab`,`
 border-bottom-left-radius: var(--n-tab-border-radius);
 border-bottom-right-radius: var(--n-tab-border-radius);
 `,[p(`active`,`
 border-top: 1px solid #0000;
 `)]),z(`tabs-tab-pad`,`
 border-top: 1px solid var(--n-tab-border-color);
 `),z(`tabs-pad`,`
 border-top: 1px solid var(--n-tab-border-color);
 `)])])]),z(`tabs-scroll-button`,[p(`start`,`
 padding-left: 10px;
 padding-right: 6px;
 `),p(`end`,`
 padding-right: 10px;
 padding-left: 6px;
 `),p(`up`,`
 padding-bottom: 10px;
 `),p(`down`,`
 padding-top: 10px;
 `)])]),Ne=b({name:`TabsButton`,props:{type:{type:String,default:`next`},mergedClsPrefix:{type:String,required:!0},vertical:Boolean,disabled:Boolean,rtl:Boolean,theme:Object,themeOverrides:Object,onClick:Function},setup(e){return{handleClick:()=>{e.disabled||e.onClick?.(e.type)}}},render(){let{mergedClsPrefix:e,disabled:t,type:n,vertical:r,rtl:i,theme:o,themeOverrides:s,handleClick:c}=this,l=n===`next`,d=r?l:i?!l:l;return w(),y(ce,{text:!0,disabled:t,size:`small`,theme:o,themeOverrides:s,onClick:c,class:u([`${e}-tabs-scroll-button`,!r&&n===`prev`&&`${e}-tabs-scroll-button--start`,!r&&n===`next`&&`${e}-tabs-scroll-button--end`,r&&n===`prev`&&`${e}-tabs-scroll-button--up`,r&&n===`next`&&`${e}-tabs-scroll-button--down`])},{icon:()=>(w(),y(V,{clsPrefix:e,style:a(r?{transform:`rotate(90deg)`}:void 0)},{default:()=>d?(w(),y(G,{key:1})):(w(),y($,{key:2}))},1032,[`clsPrefix`,`style`]))},1032,[`disabled`,`theme`,`themeOverrides`,`onClick`,`class`])}}),Pe=Ce,Fe={...te.props,value:[String,Number],defaultValue:[String,Number],trigger:{type:String,default:`click`},type:{type:String,default:`bar`},closable:Boolean,justifyContent:String,size:String,placement:{type:String,default:`top`},tabStyle:[String,Object],tabClass:String,addTabStyle:[String,Object],addTabClass:String,barWidth:Number,paneClass:String,paneStyle:[String,Object],paneWrapperClass:String,paneWrapperStyle:[String,Object],addable:[Boolean,Object],tabsPadding:{type:Number,default:0},animated:Boolean,onBeforeLeave:Function,onAdd:Function,"onUpdate:value":[Function,Array],onUpdateValue:[Function,Array],onClose:[Function,Array],labelSize:String,activeName:[String,Number],onActiveNameChange:[Function,Array],showScrollButton:Boolean,centerActiveTab:Boolean},Ie=b({name:`Tabs`,props:Fe,slots:Object,setup(e,{slots:t}){let{mergedClsPrefixRef:r,inlineThemeDisabled:i,mergedComponentPropsRef:a,mergedRtlRef:s}=n(e),c=M(`Tabs`,s,r),l=o(()=>{let{placement:t}=e;return t===`start`?c?.value?`right`:`left`:t===`end`?c?.value?`left`:`right`:t}),u=te(`Tabs`,`-tabs`,Me,ue,e,r),d=A(null),f=A(null),p=A(null),h=A(null),g=A(null),_=A(null),v=A(null),y=A(!0),b=A(!0),C=oe(e,[`labelSize`,`size`]),w=o(()=>C.value?C.value:a?.value?.Tabs?.size||`medium`),T=oe(e,[`activeName`,`value`]),D=A(T.value??e.defaultValue??(t.default?de(t.default())[0]?.props?.name:null)),O=ae(T,D),N={id:0},F=o(()=>{if(e.justifyContent&&e.type!==`card`)return{display:`flex`,justifyContent:e.justifyContent}});x(O,()=>{N.id=0,V(),P(()=>{H()})});function I(){let{value:e}=O;return e===null?null:d.value?.querySelector(`[data-name="${e}"]`)}function R(t){if(e.type===`card`)return;let{value:n}=p;if(!n)return;let i=n.style.opacity===`0`;if(t){let a=`${r.value}-tabs-bar--disabled`,{barWidth:o}=e,s=l.value;if(t.dataset.disabled===`true`?n.classList.add(a):n.classList.remove(a),[`top`,`bottom`].includes(s)){if(z([`top`,`maxHeight`,`height`]),typeof o==`number`&&t.offsetWidth>=o){let e=Math.floor((t.offsetWidth-o)/2)+t.offsetLeft;n.style.left=`${e}px`,n.style.maxWidth=`${o}px`}else n.style.left=`${t.offsetLeft}px`,n.style.maxWidth=`${t.offsetWidth}px`;n.style.width=`8192px`,i&&(n.style.transition=`none`),n.offsetWidth,i&&(n.style.transition=``,n.style.opacity=`1`)}else{if(z([`left`,`maxWidth`,`width`]),typeof o==`number`&&t.offsetHeight>=o){let e=Math.floor((t.offsetHeight-o)/2)+t.offsetTop;n.style.top=`${e}px`,n.style.maxHeight=`${o}px`}else n.style.top=`${t.offsetTop}px`,n.style.maxHeight=`${t.offsetHeight}px`;n.style.height=`8192px`,i&&(n.style.transition=`none`),n.offsetHeight,i&&(n.style.transition=``,n.style.opacity=`1`)}}}function ne(){if(e.type===`card`)return;let{value:t}=p;t&&(t.style.opacity=`0`)}function z(e){let{value:t}=p;if(t)for(let n of e)t.style[n]=``}function V(){if(e.type===`card`)return;let t=I();t?R(t):ne()}function re(e,t,n,r){let i=e.getBoundingClientRect(),a=t.getBoundingClientRect(),o=n?`left`:`top`,s=n?`right`:`bottom`,c=0;r?c=(a[o]+a[s])/2-(i[o]+i[s])/2:a[o]<i[o]?c=a[o]-i[o]:a[s]>i[s]&&(c=a[s]-i[s]),c!==0&&e.scrollBy({[o]:c,behavior:`smooth`})}function H(){let t=[`top`,`bottom`].includes(l.value),n=I();if(n){if(t){let r=_.value?.$el;if(!r)return;re(r,n,t,e.centerActiveTab)}else{let{value:r}=v;if(!r)return;re(r,n,t,e.centerActiveTab)}}}let U=A(null),W=0,G=null;function se(e){let t=U.value;if(t){W=e.getBoundingClientRect().height;let n=`${W}px`,r=()=>{t.style.height=n,t.style.maxHeight=n};G?(r(),G(),G=null):G=r}}function ce(e){let t=U.value;if(t){let n=e.getBoundingClientRect().height,r=()=>{document.body.offsetHeight,t.style.maxHeight=`${n}px`,t.style.height=`${Math.max(W,n)}px`};G?(G(),G=null,r()):G=r}}function le(){let t=U.value;if(t){t.style.maxHeight=``,t.style.height=``;let{paneWrapperStyle:n}=e;if(typeof n==`string`)t.style.cssText=n;else if(n){let{maxHeight:e,height:r}=n;e!==void 0&&(t.style.maxHeight=e),r!==void 0&&(t.style.height=r)}}}let fe={value:[]},pe=A(`next`);function me(e){let t=O.value,n=`next`;for(let r of fe.value){if(r===t)break;if(r===e){n=`prev`;break}}pe.value=n,he(e)}function he(t){let{onActiveNameChange:n,onUpdateValue:r,"onUpdate:value":i}=e;n&&S(n,t),r&&S(r,t),i&&S(i,t),D.value=t}function ge(t){let{onClose:n}=e;n&&S(n,t)}function _e(e){if([`top`,`bottom`].includes(l.value)){let{value:t}=_;if(!t)return;let n=t.$el;if(!n)return;let r=n.offsetWidth,i=!!c?.value,a=e===`next`?r:-r;n.scrollBy({left:i?-a:a,behavior:`smooth`})}else{let{value:t}=v;if(!t)return;let n=t.offsetHeight,r=e===`next`?t.scrollTop+n:t.scrollTop-n;t.scrollTo({top:r,left:0,behavior:`smooth`})}}let ve=!0;function K(){let{value:e}=p;if(!e)return;ve&&=!1;let t=`transition-disabled`;e.classList.add(t),V(),e.classList.remove(t)}let q=A(null);function J({transitionDisabled:e}){let t=d.value;if(!t)return;e&&t.classList.add(`transition-disabled`);let n=I();n&&q.value&&(q.value.style.width=`${n.offsetWidth}px`,q.value.style.height=`${n.offsetHeight}px`,q.value.style.transform=`translate(${n.offsetLeft}px, ${n.offsetTop}px)`,e&&q.value.offsetWidth),e&&t.classList.remove(`transition-disabled`)}x([O],()=>{e.type===`segment`&&P(()=>{J({transitionDisabled:!1})})}),j(()=>{e.type===`segment`&&J({transitionDisabled:!0})});let Y=0;function X(t){if(t.contentRect.width===0&&t.contentRect.height===0||Y===t.contentRect.width)return;Y=t.contentRect.width;let{type:n}=e;(n===`line`||n===`bar`)&&(ve||e.justifyContent?.startsWith(`space`))&&K(),n!==`segment`&&$(we())}let ye=Pe(X,64);function be(){let{type:t}=e;t===`line`||t===`bar`?K():t===`segment`&&J({transitionDisabled:!0})}x([()=>e.justifyContent,()=>e.size],()=>{P(()=>{(e.type===`line`||e.type===`bar`)&&K()})}),x([l,()=>c?.value],()=>{P(()=>{be(),$(we(),{instantly:!0})})}),x(()=>e.type,()=>{P(()=>{let e=f.value;e&&(e.classList.add(`transition-disabled`),be(),e.offsetWidth,e.classList.remove(`transition-disabled`))})});let Z=A(!1);function xe(e){let{target:t,contentRect:{width:n,height:r}}=e,i=t.parentElement.parentElement.offsetWidth,a=t.parentElement.parentElement.offsetHeight,o=l.value;if(!Z.value)o===`top`||o===`bottom`?i<n&&(Z.value=!0):a<r&&(Z.value=!0);else{let{value:e}=g;if(!e)return;o===`top`||o===`bottom`?i-n>e.$el.offsetWidth&&(Z.value=!1):a-r>e.$el.offsetHeight&&(Z.value=!1)}$(_.value?.$el||null)}let Se=Pe(xe,64);function Ce(){let{onAdd:t}=e;t&&t()}let Q=A(!1);function we(){let e=l.value;return(e===`top`||e===`bottom`?_.value?.$el:v.value)||null}function $(e,t={instantly:!1}){if(!e)return;let n=t.instantly?h.value:null;n&&n.classList.add(`transition-disabled`);let r=l.value;if(r===`top`||r===`bottom`){let{scrollLeft:t,scrollWidth:n,offsetWidth:r}=e,i=Math.abs(t);y.value=i<=1,b.value=i+r>=n-1,Q.value=r<n-1}else{let{scrollTop:t,scrollHeight:n,offsetHeight:r}=e;y.value=t<=1,b.value=t+r>=n-1,Q.value=r<n-1}n&&(n.offsetWidth,n.classList.remove(`transition-disabled`))}let Te=Pe(e=>{$(e.target)},64);E(Ee,{triggerRef:k(e,`trigger`),tabStyleRef:k(e,`tabStyle`),tabClassRef:k(e,`tabClass`),addTabStyleRef:k(e,`addTabStyle`),addTabClassRef:k(e,`addTabClass`),paneClassRef:k(e,`paneClass`),paneStyleRef:k(e,`paneStyle`),mergedClsPrefixRef:r,typeRef:k(e,`type`),closableRef:k(e,`closable`),valueRef:O,tabChangeIdRef:N,onBeforeLeaveRef:k(e,`onBeforeLeave`),activateTab:me,handleClose:ge,handleAdd:Ce}),ie(()=>{V(),H()}),ee(()=>{let{value:e}=h;if(!e)return;let{value:t}=r,n=`${t}-tabs-nav-scroll-wrapper--shadow-start`,i=`${t}-tabs-nav-scroll-wrapper--shadow-end`;y.value?e.classList.remove(n):e.classList.add(n),b.value?e.classList.remove(i):e.classList.add(i)});let De={syncBarPosition:()=>{V()},scrollToCurrentTab:()=>{H()}},Oe=()=>{J({transitionDisabled:!0})},ke=o(()=>{let{value:t}=w,{type:n}=e,r=`${t}${{card:`Card`,bar:`Bar`,line:`Line`,segment:`Segment`}[n]}`,{self:{barColor:i,closeIconColor:a,closeIconColorHover:o,closeIconColorPressed:s,tabColor:c,tabBorderColor:l,paneTextColor:d,tabFontWeight:f,tabBorderRadius:p,tabFontWeightActive:m,colorSegment:h,fontWeightStrong:g,tabColorSegment:_,closeSize:v,closeIconSize:y,closeColorHover:b,closeColorPressed:x,closeBorderRadius:S,[L(`panePadding`,t)]:C,[L(`tabPadding`,r)]:T,[L(`tabPaddingVertical`,r)]:E,[L(`tabGap`,r)]:D,[L(`tabGap`,`${r}Vertical`)]:O,[L(`tabTextColor`,n)]:k,[L(`tabTextColorActive`,n)]:A,[L(`tabTextColorHover`,n)]:j,[L(`tabTextColorDisabled`,n)]:M,[L(`tabFontSize`,t)]:N},common:{cubicBezierEaseInOut:P}}=u.value;return{"--n-bezier":P,"--n-color-segment":h,"--n-bar-color":i,"--n-tab-font-size":N,"--n-tab-text-color":k,"--n-tab-text-color-active":A,"--n-tab-text-color-disabled":M,"--n-tab-text-color-hover":j,"--n-pane-text-color":d,"--n-tab-border-color":l,"--n-tab-border-radius":p,"--n-close-size":v,"--n-close-icon-size":y,"--n-close-color-hover":b,"--n-close-color-pressed":x,"--n-close-border-radius":S,"--n-close-icon-color":a,"--n-close-icon-color-hover":o,"--n-close-icon-color-pressed":s,"--n-tab-color":c,"--n-tab-font-weight":f,"--n-tab-font-weight-active":m,"--n-tab-padding":T,"--n-tab-padding-vertical":E,"--n-tab-gap":D,"--n-tab-gap-vertical":O,"--n-pane-padding-left":B(C,`left`),"--n-pane-padding-right":B(C,`right`),"--n-pane-padding-top":B(C,`top`),"--n-pane-padding-bottom":B(C,`bottom`),"--n-font-weight-strong":g,"--n-tab-color-segment":_}}),Ae=i?m(`tabs`,o(()=>`${w.value[0]}${e.type[0]}`),ke,e):void 0;return{mergedClsPrefix:r,mergedValue:O,renderedNames:new Set,segmentCapsuleElRef:q,tabsPaneWrapperRef:U,tabsElRef:d,selfElRef:f,barElRef:p,addTabInstRef:g,xScrollInstRef:_,scrollWrapperElRef:h,addTabFixed:Z,tabWrapperStyle:F,handleNavResize:ye,mergedSize:w,handleScroll:Te,handleTabsResize:Se,cssVars:i?void 0:ke,themeClass:Ae?.themeClass,animationDirection:pe,renderNameListRef:fe,yScrollElRef:v,handleSegmentResize:Oe,onAnimationBeforeLeave:se,onAnimationEnter:ce,onAnimationAfterEnter:le,onRender:Ae?.onRender,startReachedRef:y,endReachedRef:b,isOverflow:Q,handleButtonClick:_e,mergedTheme:u,rtlEnabled:c,mergedPlacement:l,...De}},render(){let{mergedClsPrefix:e,type:t,mergedPlacement:n,addTabFixed:r,addable:o,mergedSize:c,renderNameListRef:d,onRender:p,paneWrapperClass:m,paneWrapperStyle:h,startReachedRef:_,endReachedRef:v,isOverflow:b,showScrollButton:x,handleButtonClick:S,mergedTheme:C,rtlEnabled:T,$slots:{default:E,prefix:D,suffix:O}}=this;p?.();let k=E?de(E()).filter(e=>e.type.__TAB_PANE__===!0):[],A=E?de(E()).filter(e=>e.type.__TAB__===!0):[],j=!A.length,M=t===`card`,P=t===`segment`,F=!M&&!P&&this.justifyContent;d.value=[];let ee=()=>{let t=(w(),s(`div`,{style:a(this.tabWrapperStyle),class:u(`${e}-tabs-wrapper`)},[F?i(()=>null):(w(),s(`div`,{key:1,class:u(`${e}-tabs-scroll-padding`),style:a(n===`top`||n===`bottom`?{width:`${this.tabsPadding}px`}:{height:`${this.tabsPadding}px`})},null,6)),j?(w(),s(l,{key:2},[i(()=>k.map((e,t)=>(d.value.push(e.props.name),Be((w(),y(je,N(e.props,{internalCreatedByPane:!0,internalLeftPadded:t!==0&&(!F||F===`center`||F===`start`||F===`end`)}),f(e.children?{default:e.children.tab}:void 0),1040,[`internalLeftPadded`]))))))],64)):(w(),s(l,{key:3},[i(()=>A.map((e,t)=>(d.value.push(e.props.name),Be(t!==0&&!F?ze(e):e))))],64)),!r&&o&&M?(w(),s(l,{key:4},[i(()=>Re(o,(j?k.length:A.length)!==0))],64)):i(()=>null),F?i(()=>null):(w(),s(`div`,{key:7,class:u(`${e}-tabs-scroll-padding`),style:a({width:`${this.tabsPadding}px`})},null,6)),M?i(()=>null):(w(),s(`div`,{key:9,ref:`barElRef`,class:u(`${e}-tabs-bar`)},null,2))],6));return w(),s(`div`,{ref:`tabsElRef`,class:u(`${e}-tabs-nav-scroll-content`)},[M&&o?(w(),y(H,{key:0,onResize:this.handleTabsResize},{default:()=>t},1032,[`onResize`])):(w(),s(l,{key:1},[i(()=>t)],64)),M?(w(),s(`div`,{key:2,class:u(`${e}-tabs-pad`)},null,2)):i(()=>null)],2)},I=P?`top`:n;return w(),s(`div`,{ref:`selfElRef`,class:u([`${e}-tabs`,this.themeClass,`${e}-tabs--${t}-type`,`${e}-tabs--${c}-size`,F&&`${e}-tabs--flex`,`${e}-tabs--${I}`,T&&`${e}-tabs--rtl`]),style:a(this.cssVars)},[g(`div`,{class:u([`${e}-tabs-nav--${t}-type`,`${e}-tabs-nav--${I}`,`${e}-tabs-nav`])},[i(()=>ne(D,t=>t&&(w(),s(`div`,{class:u(`${e}-tabs-nav__prefix`)},[i(()=>t)],2)))),P?(w(),y(H,{key:0,onResize:this.handleSegmentResize},{default:()=>(w(),s(`div`,{class:u(`${e}-tabs-rail`),ref:`tabsElRef`},[g(`div`,{class:u(`${e}-tabs-capsule`),ref:`segmentCapsuleElRef`},[g(`div`,{class:u(`${e}-tabs-wrapper`)},[g(`div`,{class:u(`${e}-tabs-tab`)},null,2)],2)],2),j?(w(),s(l,{key:0},[i(()=>k.map((e,t)=>(d.value.push(e.props.name),w(),y(je,N(e.props,{internalCreatedByPane:!0,internalLeftPadded:t!==0}),f(e.children?{default:e.children.tab}:void 0),1040,[`internalLeftPadded`]))))],64)):(w(),s(l,{key:1},[i(()=>A.map((e,t)=>(d.value.push(e.props.name),t===0?e:ze(e))))],64))],2))},1032,[`onResize`])):(w(),s(l,{key:1},[i(()=>x&&b&&(w(),y(Ne,{mergedClsPrefix:e,type:`prev`,vertical:I===`left`||I===`right`,disabled:_,rtl:!!T,theme:C.peers.Button,themeOverrides:C.peerOverrides.Button,onClick:S},null,8,[`mergedClsPrefix`,`vertical`,`disabled`,`rtl`,`theme`,`themeOverrides`,`onClick`]))),(w(),y(H,{onResize:this.handleNavResize},{default:()=>(w(),s(`div`,{class:u(`${e}-tabs-nav-scroll-wrapper`),ref:`scrollWrapperElRef`},[[`top`,`bottom`].includes(I)?(w(),y(we,{key:0,ref:`xScrollInstRef`,onScroll:this.handleScroll},{default:ee},1032,[`onScroll`])):(w(),s(`div`,{key:1,class:u(`${e}-tabs-nav-y-scroll`),onScroll:this.handleScroll,ref:`yScrollElRef`},[i(()=>ee())],42,[`onScroll`]))],2))},1032,[`onResize`])),i(()=>x&&b&&(w(),y(Ne,{mergedClsPrefix:e,type:`next`,vertical:I===`left`||I===`right`,disabled:v,rtl:!!T,theme:C.peers.Button,themeOverrides:C.peerOverrides.Button,onClick:S},null,8,[`mergedClsPrefix`,`vertical`,`disabled`,`rtl`,`theme`,`themeOverrides`,`onClick`])))],64)),r&&o&&M?(w(),s(l,{key:2},[i(()=>Re(o,!0))],64)):i(()=>null),i(()=>ne(O,t=>t&&(w(),s(`div`,{class:u(`${e}-tabs-nav__suffix`)},[i(()=>t)],2))))],2),i(()=>j&&(this.animated&&(I===`top`||I===`bottom`)?(w(),s(`div`,{key:1,ref:`tabsPaneWrapperRef`,style:a(h),class:u([`${e}-tabs-pane-wrapper`,m])},[i(()=>Le(k,this.mergedValue,this.renderedNames,this.onAnimationBeforeLeave,this.onAnimationEnter,this.onAnimationAfterEnter,this.animationDirection))],6)):Le(k,this.mergedValue,this.renderedNames)))],6)}});function Le(e,n,r,i,a,o,s){let c=[];return e.forEach(e=>{let{name:t,displayDirective:i,"display-directive":a}=e.props,o=e=>i===e||a===e,s=n===t;if(e.key!==void 0&&(e.key=t),s||o(`show`)||o(`show:lazy`)&&r.has(t)){r.has(t)||r.add(t);let n=!o(`if`);c.push(n?C(e,[[d,s]]):e)}}),s?(w(),y(t,{name:`${s}-transition`,onBeforeLeave:i,onEnter:a,onAfterEnter:o},{default:()=>c},1032,[`name`,`onBeforeLeave`,`onEnter`,`onAfterEnter`])):c}function Re(e,t){return w(),y(je,{ref:`addTabInstRef`,key:`__addable`,name:`__addable`,internalCreatedByPane:!0,internalAddable:!0,internalLeftPadded:t,disabled:typeof e==`object`&&e.disabled},null,8,[`internalLeftPadded`,`disabled`])}function ze(e){let t=_(e);return t.props?t.props.internalLeftPadded=!0:t.props={internalLeftPadded:!0},t}function Be(e){return Array.isArray(e.dynamicProps)?e.dynamicProps.includes(`internalLeftPadded`)||e.dynamicProps.push(`internalLeftPadded`):e.dynamicProps=[`internalLeftPadded`],e}export{Oe as n,Te as r,Ie as t};