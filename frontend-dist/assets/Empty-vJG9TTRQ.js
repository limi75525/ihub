import{B as e,F as t,Fn as n,Ht as r,Kt as i,Lt as a,M as o,T as s,Ut as c,Wt as l,Zt as u,dn as d,j as f,vt as p,w as m,wt as h,xt as g,yt as _}from"./vue-router-DEBuQMrJ.js";import{t as v}from"./use-locale-Bt-W1kd-.js";import{m as y}from"./client-Cn9-q7d8.js";import{t as b}from"./light-Bcn8ZZrJ.js";var x=u({name:`Empty`,render(){return(()=>{let e=f(`15c1a247ae156450`);return e[0]||=c(`svg`,{viewBox:`0 0 28 28`,fill:`none`,xmlns:`http://www.w3.org/2000/svg`},[c(`path`,{d:`M26 7.5C26 11.0899 23.0899 14 19.5 14C15.9101 14 13 11.0899 13 7.5C13 3.91015 15.9101 1 19.5 1C23.0899 1 26 3.91015 26 7.5ZM16.8536 4.14645C16.6583 3.95118 16.3417 3.95118 16.1464 4.14645C15.9512 4.34171 15.9512 4.65829 16.1464 4.85355L18.7929 7.5L16.1464 10.1464C15.9512 10.3417 15.9512 10.6583 16.1464 10.8536C16.3417 11.0488 16.6583 11.0488 16.8536 10.8536L19.5 8.20711L22.1464 10.8536C22.3417 11.0488 22.6583 11.0488 22.8536 10.8536C23.0488 10.6583 23.0488 10.3417 22.8536 10.1464L20.2071 7.5L22.8536 4.85355C23.0488 4.65829 23.0488 4.34171 22.8536 4.14645C22.6583 3.95118 22.3417 3.95118 22.1464 4.14645L19.5 6.79289L16.8536 4.14645Z`,fill:`currentColor`}),c(`path`,{d:`M25 22.75V12.5991C24.5572 13.0765 24.053 13.4961 23.5 13.8454V16H17.5L17.3982 16.0068C17.0322 16.0565 16.75 16.3703 16.75 16.75C16.75 18.2688 15.5188 19.5 14 19.5C12.4812 19.5 11.25 18.2688 11.25 16.75L11.2432 16.6482C11.1935 16.2822 10.8797 16 10.5 16H4.5V7.25C4.5 6.2835 5.2835 5.5 6.25 5.5H12.2696C12.4146 4.97463 12.6153 4.47237 12.865 4H6.25C4.45507 4 3 5.45507 3 7.25V22.75C3 24.5449 4.45507 26 6.25 26H21.75C23.5449 26 25 24.5449 25 22.75ZM4.5 22.75V17.5H9.81597L9.85751 17.7041C10.2905 19.5919 11.9808 21 14 21L14.215 20.9947C16.2095 20.8953 17.842 19.4209 18.184 17.5H23.5V22.75C23.5 23.7165 22.7165 24.5 21.75 24.5H6.25C5.2835 24.5 4.5 23.7165 4.5 22.75Z`,fill:`currentColor`})],-1)})()}}),S=_(`empty`,`
 display: flex;
 flex-direction: column;
 align-items: center;
 font-size: var(--n-font-size);
`,[g(`icon`,`
 width: var(--n-icon-size);
 height: var(--n-icon-size);
 font-size: var(--n-icon-size);
 line-height: var(--n-icon-size);
 color: var(--n-icon-color);
 transition:
 color .3s var(--n-bezier);
 `,[p(`+`,[g(`description`,`
 margin-top: 8px;
 `)])]),g(`description`,`
 transition: color .3s var(--n-bezier);
 color: var(--n-text-color);
 `),g(`extra`,`
 text-align: center;
 transition: color .3s var(--n-bezier);
 margin-top: 12px;
 color: var(--n-extra-text-color);
 `)]),C={...m.props,description:String,showDescription:{type:Boolean,default:!0},showIcon:{type:Boolean,default:!0},size:{type:String,default:`medium`},renderIcon:Function},w=u({name:`Empty`,props:C,slots:Object,setup(t){let{mergedClsPrefixRef:n,inlineThemeDisabled:i,mergedComponentPropsRef:a}=e(t),o=m(`Empty`,`-empty`,S,b,t,n),{localeRef:c}=v(`Empty`),u=r(()=>t.description??a?.value?.Empty?.description),f=r(()=>a?.value?.Empty?.renderIcon||(()=>(d(),l(x)))),p=r(()=>{let{size:e}=t,{common:{cubicBezierEaseInOut:n},self:{[h(`iconSize`,e)]:r,[h(`fontSize`,e)]:i,textColor:a,iconColor:s,extraTextColor:c}}=o.value;return{"--n-icon-size":r,"--n-font-size":i,"--n-bezier":n,"--n-text-color":a,"--n-icon-color":s,"--n-extra-text-color":c}}),g=i?s(`empty`,r(()=>{let e=``,{size:n}=t;return e+=n[0],e}),p,t):void 0;return{mergedClsPrefix:n,mergedRenderIcon:f,localizedDescription:r(()=>u.value||c.value.description),cssVars:i?void 0:p,themeClass:g?.themeClass,onRender:g?.onRender}},render(){let{$slots:e,mergedClsPrefix:r,onRender:s}=this;return s?.(),d(),i(`div`,{class:o([`${r}-empty`,this.themeClass]),style:n(this.cssVars)},[this.showIcon?(d(),i(`div`,{key:0,class:o(`${r}-empty__icon`)},[e.icon?(d(),i(a,{key:0},[t(()=>e.icon())],64)):(d(),l(y,{key:1,clsPrefix:r},{default:this.mergedRenderIcon},1032,[`clsPrefix`]))],2)):t(()=>null),this.showDescription?(d(),i(`div`,{key:2,class:o(`${r}-empty__description`)},[e.default?(d(),i(a,{key:0},[t(()=>e.default())],64)):(d(),i(a,{key:1},[t(()=>this.localizedDescription)],64))],2)):t(()=>null),e.extra?(d(),i(`div`,{key:4,class:o(`${r}-empty__extra`)},[t(()=>e.extra())],2)):t(()=>null)],6)}});export{w as t};