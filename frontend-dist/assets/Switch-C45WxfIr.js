import{B as e,Ct as t,D as n,E as r,F as i,Fn as a,Ht as o,Kt as s,M as c,St as l,T as u,Ut as d,Wt as f,Zt as p,b as m,c as h,d as g,dn as _,g as v,jn as y,kn as b,nn as x,p as S,u as C,vt as w,w as T,wt as E,xt as D,y as O,yt as k}from"./vue-router-DEBuQMrJ.js";import{_ as A,h as j}from"./client-Cn9-q7d8.js";import{t as M}from"./use-merged-state-C_DmUKj7.js";import{l as N}from"./index-B3UrI3qt.js";function P(e){let{primaryColor:t,opacityDisabled:r,borderRadius:i,textColor3:a}=e;return{...N,iconColor:a,textColor:`white`,loadingColor:t,opacityDisabled:r,railColor:`rgba(0, 0, 0, .14)`,railColorActive:t,buttonBoxShadow:`0 1px 4px 0 rgba(0, 0, 0, 0.3), inset 0 0 1px 0 rgba(0, 0, 0, 0.05)`,buttonColor:`#FFF`,railBorderRadiusSmall:i,railBorderRadiusMedium:i,railBorderRadiusLarge:i,buttonBorderRadiusSmall:i,buttonBorderRadiusMedium:i,buttonBorderRadiusLarge:i,boxShadowFocus:`0 0 0 2px ${n(t,{alpha:.2})}`}}var F={name:`Switch`,common:r,self:P},I=k(`switch`,`
 height: var(--n-height);
 min-width: var(--n-width);
 vertical-align: middle;
 user-select: none;
 -webkit-user-select: none;
 display: inline-flex;
 outline: none;
 justify-content: center;
 align-items: center;
`,[D(`children-placeholder`,`
 height: var(--n-rail-height);
 display: flex;
 flex-direction: column;
 overflow: hidden;
 pointer-events: none;
 visibility: hidden;
 `),D(`rail-placeholder`,`
 display: flex;
 flex-wrap: none;
 `),D(`button-placeholder`,`
 width: calc(1.75 * var(--n-rail-height));
 height: var(--n-rail-height);
 `),k(`base-loading`,`
 position: absolute;
 top: 50%;
 left: 50%;
 transform: translateX(-50%) translateY(-50%);
 font-size: calc(var(--n-button-width) - 4px);
 color: var(--n-loading-color);
 transition: color .3s var(--n-bezier);
 `,[C({left:`50%`,top:`50%`,originalTransform:`translateX(-50%) translateY(-50%)`})]),D(`checked, unchecked`,`
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
 `),D(`checked`,`
 right: 0;
 padding-right: calc(1.25 * var(--n-rail-height) - var(--n-offset));
 `),D(`unchecked`,`
 left: 0;
 justify-content: flex-end;
 padding-left: calc(1.25 * var(--n-rail-height) - var(--n-offset));
 `),w(`&:focus`,[D(`rail`,`
 box-shadow: var(--n-box-shadow-focus);
 `)]),l(`round`,[D(`rail`,`border-radius: calc(var(--n-rail-height) / 2);`,[D(`button`,`border-radius: calc(var(--n-button-height) / 2);`)])]),t(`disabled`,[t(`icon`,[l(`rubber-band`,[l(`pressed`,[D(`rail`,[D(`button`,`max-width: var(--n-button-width-pressed);`)])]),D(`rail`,[w(`&:active`,[D(`button`,`max-width: var(--n-button-width-pressed);`)])]),l(`active`,[l(`pressed`,[D(`rail`,[D(`button`,`left: calc(100% - var(--n-offset) - var(--n-button-width-pressed));`)])]),D(`rail`,[w(`&:active`,[D(`button`,`left: calc(100% - var(--n-offset) - var(--n-button-width-pressed));`)])])])])])]),l(`active`,[D(`rail`,[D(`button`,`left: calc(100% - var(--n-button-width) - var(--n-offset))`)])]),D(`rail`,`
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
 `,[D(`button-icon`,`
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
 `,[C()]),D(`button`,`
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
 `)]),l(`active`,[D(`rail`,`background-color: var(--n-rail-color-active);`)]),l(`loading`,[D(`rail`,`
 cursor: wait;
 `)]),l(`disabled`,[D(`rail`,`
 cursor: not-allowed;
 opacity: .5;
 `)])]),L=[`aria-checked`,`tabindex`,`onClick`,`onFocus`,`onBlur`,`onKeyup`,`onKeydown`],R={...T.props,size:String,value:{type:[String,Number,Boolean],default:void 0},loading:Boolean,defaultValue:{type:[String,Number,Boolean],default:!1},disabled:{type:Boolean,default:void 0},round:{type:Boolean,default:!0},"onUpdate:value":[Function,Array],onUpdateValue:[Function,Array],checkedValue:{type:[String,Number,Boolean],default:!0},uncheckedValue:{type:[String,Number,Boolean],default:!1},railStyle:Function,rubberBand:{type:Boolean,default:!0},spinProps:Object,onChange:[Function,Array]},z,B=p({name:`Switch`,props:R,slots:Object,setup(t){z===void 0&&(z=typeof CSS<`u`?CSS.supports!==void 0&&CSS.supports(`width`,`max(1px)`):!0);let{mergedClsPrefixRef:n,inlineThemeDisabled:r,mergedComponentPropsRef:i}=e(t),a=T(`Switch`,`-switch`,I,F,t,n),s=S(t,{mergedSize(e){return t.size===void 0?e?e.mergedSize.value:i?.value?.Switch?.size||`medium`:t.size}}),{mergedSizeRef:c,mergedDisabledRef:l}=s,d=b(t.defaultValue),f=y(t,`value`),p=M(f,d),h=o(()=>p.value===t.checkedValue),g=b(!1),_=b(!1),v=o(()=>{let{railStyle:e}=t;if(e)return e({focused:_.value,checked:h.value})});function x(e){let{"onUpdate:value":n,onChange:r,onUpdateValue:i}=t,{nTriggerFormInput:a,nTriggerFormChange:o}=s;n&&m(n,e),i&&m(i,e),r&&m(r,e),d.value=e,a(),o()}function C(){let{nTriggerFormFocus:e}=s;e()}function w(){let{nTriggerFormBlur:e}=s;e()}function D(){t.loading||l.value||(p.value===t.checkedValue?x(t.uncheckedValue):x(t.checkedValue))}function O(){_.value=!0,C()}function k(){_.value=!1,w(),g.value=!1}function N(e){t.loading||l.value||e.key===` `&&(p.value===t.checkedValue?x(t.uncheckedValue):x(t.checkedValue),g.value=!1)}function P(e){t.loading||l.value||e.key===` `&&(e.preventDefault(),g.value=!0)}let L=o(()=>{let{value:e}=c,{self:{opacityDisabled:t,railColor:n,railColorActive:r,buttonBoxShadow:i,buttonColor:o,boxShadowFocus:s,loadingColor:l,textColor:u,iconColor:d,[E(`buttonHeight`,e)]:f,[E(`buttonWidth`,e)]:p,[E(`buttonWidthPressed`,e)]:m,[E(`railHeight`,e)]:h,[E(`railWidth`,e)]:g,[E(`railBorderRadius`,e)]:_,[E(`buttonBorderRadius`,e)]:v},common:{cubicBezierEaseInOut:y}}=a.value,b,x,S;return z?(b=`calc((${h} - ${f}) / 2)`,x=`max(${h}, ${f})`,S=`max(${g}, calc(${g} + ${f} - ${h}))`):(b=A((j(h)-j(f))/2),x=A(Math.max(j(h),j(f))),S=j(h)>j(f)?g:A(j(g)+j(f)-j(h))),{"--n-bezier":y,"--n-button-border-radius":v,"--n-button-box-shadow":i,"--n-button-color":o,"--n-button-width":p,"--n-button-width-pressed":m,"--n-button-height":f,"--n-height":x,"--n-offset":b,"--n-opacity-disabled":t,"--n-rail-border-radius":_,"--n-rail-color":n,"--n-rail-color-active":r,"--n-rail-height":h,"--n-rail-width":g,"--n-width":S,"--n-box-shadow-focus":s,"--n-loading-color":l,"--n-text-color":u,"--n-icon-color":d}}),R=r?u(`switch`,o(()=>c.value[0]),L,t):void 0;return{handleClick:D,handleBlur:k,handleFocus:O,handleKeyup:N,handleKeydown:P,mergedRailStyle:v,pressed:g,mergedClsPrefix:n,mergedValue:p,checked:h,mergedDisabled:l,cssVars:r?void 0:L,themeClass:R?.themeClass,onRender:R?.onRender}},render(){let{mergedClsPrefix:e,mergedDisabled:t,checked:n,mergedRailStyle:r,onRender:o,$slots:l}=this;o?.();let{checked:u,unchecked:p,icon:m,"checked-icon":y,"unchecked-icon":b}=l,S=!(v(m)&&v(y)&&v(b));return _(),s(`div`,{role:`switch`,"aria-checked":n,class:c([`${e}-switch`,this.themeClass,S&&`${e}-switch--icon`,n&&`${e}-switch--active`,t&&`${e}-switch--disabled`,this.round&&`${e}-switch--round`,this.loading&&`${e}-switch--loading`,this.pressed&&`${e}-switch--pressed`,this.rubberBand&&`${e}-switch--rubber-band`]),tabindex:this.mergedDisabled?void 0:0,style:a(this.cssVars),onClick:this.handleClick,onFocus:this.handleFocus,onBlur:this.handleBlur,onKeyup:this.handleKeyup,onKeydown:this.handleKeydown},[d(`div`,{class:c(`${e}-switch__rail`),"aria-hidden":`true`,style:a(r)},[i(()=>O(u,t=>O(p,n=>t||n?(_(),s(`div`,{key:4,"aria-hidden":!0,class:c(`${e}-switch__children-placeholder`)},[d(`div`,{class:c(`${e}-switch__rail-placeholder`)},[d(`div`,{class:c(`${e}-switch__button-placeholder`)},null,2),i(()=>t)],2),d(`div`,{class:c(`${e}-switch__rail-placeholder`)},[d(`div`,{class:c(`${e}-switch__button-placeholder`)},null,2),i(()=>n)],2)],2)):null))),d(`div`,{class:c(`${e}-switch__button`)},[i(()=>O(m,t=>O(y,n=>O(b,r=>(_(),f(g,null,{default:()=>this.loading?(_(),f(h,x({key:`loading`,clsPrefix:e,strokeWidth:20},this.spinProps),null,16,[`clsPrefix`])):this.checked&&(n||t)?(_(),s(`div`,{class:c(`${e}-switch__button-icon`),key:n?`checked-icon`:`icon`},[i(()=>n||t)],2)):!this.checked&&(r||t)?(_(),s(`div`,{class:c(`${e}-switch__button-icon`),key:r?`unchecked-icon`:`icon`},[i(()=>r||t)],2)):null},1024)))))),i(()=>O(u,t=>t&&(_(),s(`div`,{key:`checked`,class:c(`${e}-switch__checked`)},[i(()=>t)],2)))),i(()=>O(p,t=>t&&(_(),s(`div`,{key:`unchecked`,class:c(`${e}-switch__unchecked`)},[i(()=>t)],2))))],2)],6)],46,L)}});export{B as t};