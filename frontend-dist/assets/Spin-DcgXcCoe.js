import{$n as e,C as t,Ht as n,In as r,J as i,K as a,L as o,R as s,Rt as c,Wt as l,Yt as u,Z as d,_ as f,cn as p,dn as m,gn as h,hn as g,kn as _,ln as v,nt as y,qn as b,sn as x,v as S,zt as C}from"./vue-router-CtlYBEfb.js";import{t as w}from"./use-compitable-DV_ltLkJ.js";import{u as T}from"./index-1sxyyN4B.js";var E=c([c(`@keyframes spin-rotate`,`
 from {
 transform: rotate(0);
 }
 to {
 transform: rotate(360deg);
 }
 `),C(`spin-container`,`
 position: relative;
 `,[C(`spin-body`,`
 position: absolute;
 top: 50%;
 left: 50%;
 transform: translateX(-50%) translateY(-50%);
 `,[t()])]),C(`spin-body`,`
 display: inline-flex;
 align-items: center;
 justify-content: center;
 flex-direction: column;
 `),C(`spin`,`
 display: inline-flex;
 height: var(--n-size);
 width: var(--n-size);
 font-size: var(--n-size);
 color: var(--n-color);
 `,[n(`rotate`,`
 animation: spin-rotate 2s linear infinite;
 `)]),C(`spin-description`,`
 display: inline-block;
 font-size: var(--n-font-size);
 color: var(--n-text-color);
 transition: color .3s var(--n-bezier);
 margin-top: 8px;
 `),C(`spin-content`,`
 opacity: 1;
 transition: opacity .3s var(--n-bezier);
 pointer-events: all;
 `,[n(`spinning`,`
 user-select: none;
 -webkit-user-select: none;
 pointer-events: none;
 opacity: var(--n-opacity-spinning);
 `)])]),D={small:20,medium:18,large:16},O={...o.props,contentClass:String,contentStyle:[Object,String],description:String,size:{type:[String,Number],default:`medium`},show:{type:Boolean,default:!0},rotate:{type:Boolean,default:!0},spinning:{type:Boolean,validator:()=>!0,default:void 0},delay:Number,...S,strokeWidth:Number},k=h({name:`Spin`,props:O,slots:Object,setup(e){let{mergedClsPrefixRef:t,inlineThemeDisabled:n}=y(e),i=o(`Spin`,`-spin`,E,T,e,t),c=x(()=>{let{size:t}=e,{common:{cubicBezierEaseInOut:n},self:r}=i.value,{opacitySpinning:o,color:s,textColor:c}=r;return{"--n-bezier":n,"--n-opacity-spinning":o,"--n-size":typeof t==`number`?a(t):r[l(`size`,t)],"--n-color":s,"--n-text-color":c}}),u=n?s(`spin`,x(()=>{let{size:t}=e;return typeof t==`number`?String(t):t[0]}),c,e):void 0,d=w(e,[`spinning`,`show`]),f=b(!1);return r(t=>{let n;if(d.value){let{delay:r}=e;if(r){n=window.setTimeout(()=>{f.value=!0},r),t(()=>{clearTimeout(n)});return}}f.value=d.value}),{mergedClsPrefix:t,active:f,mergedStrokeWidth:x(()=>{let{strokeWidth:t}=e;if(t!==void 0)return t;let{size:n}=e;return D[typeof n==`number`?`medium`:n]}),cssVars:n?void 0:c,themeClass:u?.themeClass,onRender:u?.onRender}},render(){let{$slots:t,mergedClsPrefix:n,description:r}=this,a=t.icon&&this.rotate,o=(r||t.description)&&(_(),m(`div`,{class:i(`${n}-spin-description`)},[d(()=>r||t.description?.())],2)),s=t.icon?(_(),m(`div`,{key:1,class:i([`${n}-spin-body`,this.themeClass])},[p(`div`,{class:i([`${n}-spin`,a&&`${n}-spin--rotate`]),style:e(t.default?``:this.cssVars)},[d(()=>t.icon())],6),d(()=>o)],2)):(_(),m(`div`,{key:2,class:i([`${n}-spin-body`,this.themeClass])},[(_(),v(f,{clsPrefix:n,style:e(t.default?``:this.cssVars),stroke:this.stroke,"stroke-width":this.mergedStrokeWidth,radius:this.radius,scale:this.scale,class:i(`${n}-spin`)},null,8,[`clsPrefix`,`style`,`stroke`,`stroke-width`,`radius`,`scale`,`class`])),d(()=>o)],2));return this.onRender?.(),t.default?(_(),m(`div`,{key:3,class:i([`${n}-spin-container`,this.themeClass]),style:e(this.cssVars)},[p(`div`,{class:i([`${n}-spin-content`,this.active&&`${n}-spin-content--spinning`,this.contentClass]),style:e(this.contentStyle)},[d(()=>t.default?.())],6),g(u,{name:`fade-in-transition`},{default:()=>this.active?s:null},1024)],6)):s}});export{k as t};