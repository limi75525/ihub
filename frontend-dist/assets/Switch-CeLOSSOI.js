import{$n as e,A as t,B as n,E as r,Ht as i,J as a,K as o,L as s,R as c,Rt as l,S as u,Ut as d,Vt as f,W as p,Wt as m,Yn as h,Z as g,_,b as v,cn as y,dn as b,gn as x,k as S,kn as C,ln as w,nt as T,qn as E,sn as D,xn as O,y as k,z as A,zt as j}from"./vue-router-CtlYBEfb.js";import{t as M}from"./use-merged-state-vBUfWV25.js";import{l as N}from"./index-1sxyyN4B.js";function P(e){let{primaryColor:t,opacityDisabled:r,borderRadius:i,textColor3:a}=e;return{...N,iconColor:a,textColor:`white`,loadingColor:t,opacityDisabled:r,railColor:`rgba(0, 0, 0, .14)`,railColorActive:t,buttonBoxShadow:`0 1px 4px 0 rgba(0, 0, 0, 0.3), inset 0 0 1px 0 rgba(0, 0, 0, 0.05)`,buttonColor:`#FFF`,railBorderRadiusSmall:i,railBorderRadiusMedium:i,railBorderRadiusLarge:i,buttonBorderRadiusSmall:i,buttonBorderRadiusMedium:i,buttonBorderRadiusLarge:i,boxShadowFocus:`0 0 0 2px ${n(t,{alpha:.2})}`}}var F={name:`Switch`,common:A,self:P},I=j(`switch`,`
 height: var(--n-height);
 min-width: var(--n-width);
 vertical-align: middle;
 user-select: none;
 -webkit-user-select: none;
 display: inline-flex;
 outline: none;
 justify-content: center;
 align-items: center;
`,[f(`children-placeholder`,`
 height: var(--n-rail-height);
 display: flex;
 flex-direction: column;
 overflow: hidden;
 pointer-events: none;
 visibility: hidden;
 `),f(`rail-placeholder`,`
 display: flex;
 flex-wrap: none;
 `),f(`button-placeholder`,`
 width: calc(1.75 * var(--n-rail-height));
 height: var(--n-rail-height);
 `),j(`base-loading`,`
 position: absolute;
 top: 50%;
 left: 50%;
 transform: translateX(-50%) translateY(-50%);
 font-size: calc(var(--n-button-width) - 4px);
 color: var(--n-loading-color);
 transition: color .3s var(--n-bezier);
 `,[k({left:`50%`,top:`50%`,originalTransform:`translateX(-50%) translateY(-50%)`})]),f(`checked, unchecked`,`
 transition: color .3s var(--n-bezier);
 color: var(--n-text-color);
 box-sizing: border-box;
 position: absolute;
 white-space: nowrap;
 top: 0;
 bottom: 0;
 display: flex;
 align-items: center;
 line-height: 1;
 `),f(`checked`,`
 right: 0;
 padding-right: calc(1.25 * var(--n-rail-height) - var(--n-offset));
 `),f(`unchecked`,`
 left: 0;
 justify-content: flex-end;
 padding-left: calc(1.25 * var(--n-rail-height) - var(--n-offset));
 `),l(`&:focus`,[f(`rail`,`
 box-shadow: var(--n-box-shadow-focus);
 `)]),i(`round`,[f(`rail`,`border-radius: calc(var(--n-rail-height) / 2);`,[f(`button`,`border-radius: calc(var(--n-button-height) / 2);`)])]),d(`disabled`,[d(`icon`,[i(`rubber-band`,[i(`pressed`,[f(`rail`,[f(`button`,`max-width: var(--n-button-width-pressed);`)])]),f(`rail`,[l(`&:active`,[f(`button`,`max-width: var(--n-button-width-pressed);`)])]),i(`active`,[i(`pressed`,[f(`rail`,[f(`button`,`left: calc(100% - var(--n-offset) - var(--n-button-width-pressed));`)])]),f(`rail`,[l(`&:active`,[f(`button`,`left: calc(100% - var(--n-offset) - var(--n-button-width-pressed));`)])])])])])]),i(`active`,[f(`rail`,[f(`button`,`left: calc(100% - var(--n-button-width) - var(--n-offset))`)])]),f(`rail`,`
 overflow: hidden;
 height: var(--n-rail-height);
 min-width: var(--n-rail-width);
 border-radius: var(--n-rail-border-radius);
 cursor: pointer;
 position: relative;
 transition:
 opacity .3s var(--n-bezier),
 background .3s var(--n-bezier),
 box-shadow .3s var(--n-bezier);
 background-color: var(--n-rail-color);
 `,[f(`button-icon`,`
 color: var(--n-icon-color);
 transition: color .3s var(--n-bezier);
 font-size: calc(var(--n-button-height) - 4px);
 position: absolute;
 left: 0;
 right: 0;
 top: 0;
 bottom: 0;
 display: flex;
 justify-content: center;
 align-items: center;
 line-height: 1;
 `,[k()]),f(`button`,`
 align-items: center; 
 top: var(--n-offset);
 left: var(--n-offset);
 height: var(--n-button-height);
 width: var(--n-button-width-pressed);
 max-width: var(--n-button-width);
 border-radius: var(--n-button-border-radius);
 background-color: var(--n-button-color);
 box-shadow: var(--n-button-box-shadow);
 box-sizing: border-box;
 cursor: inherit;
 content: "";
 position: absolute;
 transition:
 background-color .3s var(--n-bezier),
 left .3s var(--n-bezier),
 opacity .3s var(--n-bezier),
 max-width .3s var(--n-bezier),
 box-shadow .3s var(--n-bezier);
 `)]),i(`active`,[f(`rail`,`background-color: var(--n-rail-color-active);`)]),i(`loading`,[f(`rail`,`
 cursor: wait;
 `)]),i(`disabled`,[f(`rail`,`
 cursor: not-allowed;
 opacity: .5;
 `)])]),L=[`aria-checked`,`tabindex`,`onClick`,`onFocus`,`onBlur`,`onKeyup`,`onKeydown`],R={...s.props,size:String,value:{type:[String,Number,Boolean],default:void 0},loading:Boolean,defaultValue:{type:[String,Number,Boolean],default:!1},disabled:{type:Boolean,default:void 0},round:{type:Boolean,default:!0},"onUpdate:value":[Function,Array],onUpdateValue:[Function,Array],checkedValue:{type:[String,Number,Boolean],default:!0},uncheckedValue:{type:[String,Number,Boolean],default:!1},railStyle:Function,rubberBand:{type:Boolean,default:!0},spinProps:Object,onChange:[Function,Array]},z,B=x({name:`Switch`,props:R,slots:Object,setup(e){z===void 0&&(z=typeof CSS<`u`?CSS.supports!==void 0&&CSS.supports(`width`,`max(1px)`):!0);let{mergedClsPrefixRef:n,inlineThemeDisabled:r,mergedComponentPropsRef:i}=T(e),a=s(`Switch`,`-switch`,I,F,e,n),l=u(e,{mergedSize(t){return e.size===void 0?t?t.mergedSize.value:i?.value?.Switch?.size||`medium`:e.size}}),{mergedSizeRef:d,mergedDisabledRef:f}=l,g=E(e.defaultValue),_=h(e,`value`),v=M(_,g),y=D(()=>v.value===e.checkedValue),b=E(!1),x=E(!1),S=D(()=>{let{railStyle:t}=e;if(t)return t({focused:x.value,checked:y.value})});function C(n){let{"onUpdate:value":r,onChange:i,onUpdateValue:a}=e,{nTriggerFormInput:o,nTriggerFormChange:s}=l;r&&t(r,n),a&&t(a,n),i&&t(i,n),g.value=n,o(),s()}function w(){let{nTriggerFormFocus:e}=l;e()}function O(){let{nTriggerFormBlur:e}=l;e()}function k(){e.loading||f.value||(v.value===e.checkedValue?C(e.uncheckedValue):C(e.checkedValue))}function A(){x.value=!0,w()}function j(){x.value=!1,O(),b.value=!1}function N(t){e.loading||f.value||t.key===` `&&(v.value===e.checkedValue?C(e.uncheckedValue):C(e.checkedValue),b.value=!1)}function P(t){e.loading||f.value||t.key===` `&&(t.preventDefault(),b.value=!0)}let L=D(()=>{let{value:e}=d,{self:{opacityDisabled:t,railColor:n,railColorActive:r,buttonBoxShadow:i,buttonColor:s,boxShadowFocus:c,loadingColor:l,textColor:u,iconColor:f,[m(`buttonHeight`,e)]:h,[m(`buttonWidth`,e)]:g,[m(`buttonWidthPressed`,e)]:_,[m(`railHeight`,e)]:v,[m(`railWidth`,e)]:y,[m(`railBorderRadius`,e)]:b,[m(`buttonBorderRadius`,e)]:x},common:{cubicBezierEaseInOut:S}}=a.value,C,w,T;return z?(C=`calc((${v} - ${h}) / 2)`,w=`max(${v}, ${h})`,T=`max(${y}, calc(${y} + ${h} - ${v}))`):(C=o((p(v)-p(h))/2),w=o(Math.max(p(v),p(h))),T=p(v)>p(h)?y:o(p(y)+p(h)-p(v))),{"--n-bezier":S,"--n-button-border-radius":x,"--n-button-box-shadow":i,"--n-button-color":s,"--n-button-width":g,"--n-button-width-pressed":_,"--n-button-height":h,"--n-height":w,"--n-offset":C,"--n-opacity-disabled":t,"--n-rail-border-radius":b,"--n-rail-color":n,"--n-rail-color-active":r,"--n-rail-height":v,"--n-rail-width":y,"--n-width":T,"--n-box-shadow-focus":c,"--n-loading-color":l,"--n-text-color":u,"--n-icon-color":f}}),R=r?c(`switch`,D(()=>d.value[0]),L,e):void 0;return{handleClick:k,handleBlur:j,handleFocus:A,handleKeyup:N,handleKeydown:P,mergedRailStyle:S,pressed:b,mergedClsPrefix:n,mergedValue:v,checked:y,mergedDisabled:f,cssVars:r?void 0:L,themeClass:R?.themeClass,onRender:R?.onRender}},render(){let{mergedClsPrefix:t,mergedDisabled:n,checked:i,mergedRailStyle:o,onRender:s,$slots:c}=this;s?.();let{checked:l,unchecked:u,icon:d,"checked-icon":f,"unchecked-icon":p}=c,m=!(r(d)&&r(f)&&r(p));return C(),b(`div`,{role:`switch`,"aria-checked":i,class:a([`${t}-switch`,this.themeClass,m&&`${t}-switch--icon`,i&&`${t}-switch--active`,n&&`${t}-switch--disabled`,this.round&&`${t}-switch--round`,this.loading&&`${t}-switch--loading`,this.pressed&&`${t}-switch--pressed`,this.rubberBand&&`${t}-switch--rubber-band`]),tabindex:this.mergedDisabled?void 0:0,style:e(this.cssVars),onClick:this.handleClick,onFocus:this.handleFocus,onBlur:this.handleBlur,onKeyup:this.handleKeyup,onKeydown:this.handleKeydown},[y(`div`,{class:a(`${t}-switch__rail`),"aria-hidden":`true`,style:e(o)},[g(()=>S(l,e=>S(u,n=>e||n?(C(),b(`div`,{key:4,"aria-hidden":!0,class:a(`${t}-switch__children-placeholder`)},[y(`div`,{class:a(`${t}-switch__rail-placeholder`)},[y(`div`,{class:a(`${t}-switch__button-placeholder`)},null,2),g(()=>e)],2),y(`div`,{class:a(`${t}-switch__rail-placeholder`)},[y(`div`,{class:a(`${t}-switch__button-placeholder`)},null,2),g(()=>n)],2)],2)):null))),y(`div`,{class:a(`${t}-switch__button`)},[g(()=>S(d,e=>S(f,n=>S(p,r=>(C(),w(v,null,{default:()=>this.loading?(C(),w(_,O({key:`loading`,clsPrefix:t,strokeWidth:20},this.spinProps),null,16,[`clsPrefix`])):this.checked&&(n||e)?(C(),b(`div`,{class:a(`${t}-switch__button-icon`),key:n?`checked-icon`:`icon`},[g(()=>n||e)],2)):!this.checked&&(r||e)?(C(),b(`div`,{class:a(`${t}-switch__button-icon`),key:r?`unchecked-icon`:`icon`},[g(()=>r||e)],2)):null},1024)))))),g(()=>S(l,e=>e&&(C(),b(`div`,{key:`checked`,class:a(`${t}-switch__checked`)},[g(()=>e)],2)))),g(()=>S(u,e=>e&&(C(),b(`div`,{key:`unchecked`,class:a(`${t}-switch__unchecked`)},[g(()=>e)],2))))],2)],6)],46,L)}});export{B as t};