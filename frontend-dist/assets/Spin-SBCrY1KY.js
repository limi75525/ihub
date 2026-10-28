import{B as e,F as t,Fn as n,Ht as r,Kt as i,M as a,St as o,T as s,Ut as c,Wt as l,Xt as u,Zt as d,c as f,dn as p,kn as m,kt as h,l as g,vn as _,vt as v,w as y,wt as b,yt as x}from"./vue-router-DEBuQMrJ.js";import{_ as S,d as C}from"./client-Cn9-q7d8.js";import{t as w}from"./use-compitable-CZxTzUvH.js";import{u as T}from"./index-B3UrI3qt.js";var E=v([v(`@keyframes spin-rotate`,`
 from {
 transform: rotate(0);
 }
 to {
 transform: rotate(360deg);
 }
 `),x(`spin-container`,`
 position: relative;
 `,[x(`spin-body`,`
 position: absolute;
 top: 50%;
 left: 50%;
 transform: translateX(-50%) translateY(-50%);
 `,[C()])]),x(`spin-body`,`
 display: inline-flex;
 align-items: center;
 justify-content: center;
 flex-direction: column;
 `),x(`spin`,`
 display: inline-flex;
 height: var(--n-size);
 width: var(--n-size);
 font-size: var(--n-size);
 color: var(--n-color);
 `,[o(`rotate`,`
 animation: spin-rotate 2s linear infinite;
 `)]),x(`spin-description`,`
 display: inline-block;
 font-size: var(--n-font-size);
 color: var(--n-text-color);
 transition: color .3s var(--n-bezier);
 margin-top: 8px;
 `),x(`spin-content`,`
 opacity: 1;
 transition: opacity .3s var(--n-bezier);
 pointer-events: all;
 `,[o(`spinning`,`
 user-select: none;
 -webkit-user-select: none;
 pointer-events: none;
 opacity: var(--n-opacity-spinning);
 `)])]),D={small:20,medium:18,large:16},O={...y.props,contentClass:String,contentStyle:[Object,String],description:String,size:{type:[String,Number],default:`medium`},show:{type:Boolean,default:!0},rotate:{type:Boolean,default:!0},spinning:{type:Boolean,validator:()=>!0,default:void 0},delay:Number,...g,strokeWidth:Number},k=d({name:`Spin`,props:O,slots:Object,setup(t){let{mergedClsPrefixRef:n,inlineThemeDisabled:i}=e(t),a=y(`Spin`,`-spin`,E,T,t,n),o=r(()=>{let{size:e}=t,{common:{cubicBezierEaseInOut:n},self:r}=a.value,{opacitySpinning:i,color:o,textColor:s}=r;return{"--n-bezier":n,"--n-opacity-spinning":i,"--n-size":typeof e==`number`?S(e):r[b(`size`,e)],"--n-color":o,"--n-text-color":s}}),c=i?s(`spin`,r(()=>{let{size:e}=t;return typeof e==`number`?String(e):e[0]}),o,t):void 0,l=w(t,[`spinning`,`show`]),u=m(!1);return _(e=>{let n;if(l.value){let{delay:r}=t;if(r){n=window.setTimeout(()=>{u.value=!0},r),e(()=>{clearTimeout(n)});return}}u.value=l.value}),{mergedClsPrefix:n,active:u,mergedStrokeWidth:r(()=>{let{strokeWidth:e}=t;if(e!==void 0)return e;let{size:n}=t;return D[typeof n==`number`?`medium`:n]}),cssVars:i?void 0:o,themeClass:c?.themeClass,onRender:c?.onRender}},render(){let{$slots:e,mergedClsPrefix:r,description:o}=this,s=e.icon&&this.rotate,d=(o||e.description)&&(p(),i(`div`,{class:a(`${r}-spin-description`)},[t(()=>o||e.description?.())],2)),m=e.icon?(p(),i(`div`,{key:1,class:a([`${r}-spin-body`,this.themeClass])},[c(`div`,{class:a([`${r}-spin`,s&&`${r}-spin--rotate`]),style:n(e.default?``:this.cssVars)},[t(()=>e.icon())],6),t(()=>d)],2)):(p(),i(`div`,{key:2,class:a([`${r}-spin-body`,this.themeClass])},[(p(),l(f,{clsPrefix:r,style:n(e.default?``:this.cssVars),stroke:this.stroke,"stroke-width":this.mergedStrokeWidth,radius:this.radius,scale:this.scale,class:a(`${r}-spin`)},null,8,[`clsPrefix`,`style`,`stroke`,`stroke-width`,`radius`,`scale`,`class`])),t(()=>d)],2));return this.onRender?.(),e.default?(p(),i(`div`,{key:3,class:a([`${r}-spin-container`,this.themeClass]),style:n(this.cssVars)},[c(`div`,{class:a([`${r}-spin-content`,this.active&&`${r}-spin-content--spinning`,this.contentClass]),style:n(this.contentStyle)},[t(()=>e.default?.())],6),u(h,{name:`fade-in-transition`},{default:()=>this.active?m:null},1024)],6)):m}});export{k as t};