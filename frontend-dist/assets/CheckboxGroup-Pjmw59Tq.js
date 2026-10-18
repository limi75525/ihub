import{$n as e,A as t,An as n,Gt as r,Ht as i,J as a,Kt as o,L as s,M as c,P as l,R as u,Rt as d,S as f,Vt as p,Wt as m,Yn as h,Z as g,at as _,b as v,bn as y,cn as b,dn as x,gn as S,hn as C,k as w,kn as T,ln as E,nt as D,q as O,qn as k,rn as A,sn as j,w as M,y as N,zt as P}from"./vue-router-CtlYBEfb.js";import{t as F}from"./misc-DDs3MKLt.js";import{t as I}from"./use-merged-state-vBUfWV25.js";import{A as L}from"./index-1sxyyN4B.js";var R=()=>(()=>{let e=O(`75be776d8875fa17`);return e[0]||=b(`svg`,{viewBox:`0 0 64 64`,class:`check-icon`},[b(`path`,{d:`M50.42,16.76L22.34,39.45l-8.1-11.46c-1.12-1.58-3.3-1.96-4.88-0.84c-1.58,1.12-1.95,3.3-0.84,4.88l10.26,14.51  c0.56,0.79,1.42,1.31,2.38,1.45c0.16,0.02,0.32,0.03,0.48,0.03c0.8,0,1.57-0.27,2.2-0.78l30.99-25.03c1.5-1.21,1.74-3.42,0.52-4.92  C54.13,15.78,51.93,15.55,50.42,16.76z`})],-1)})(),z=()=>(()=>{let e=O(`c6eed899356c8404`);return e[0]||=b(`svg`,{viewBox:`0 0 100 100`,class:`line-icon`},[b(`path`,{d:`M80.2,55.5H21.4c-2.8,0-5.1-2.5-5.1-5.5l0,0c0-3,2.3-5.5,5.1-5.5h58.7c2.8,0,5.1,2.5,5.1,5.5l0,0C85.2,53.1,82.9,55.5,80.2,55.5z`})],-1)})(),B=d([P(`checkbox`,`
 font-size: var(--n-font-size);
 outline: none;
 cursor: pointer;
 display: inline-flex;
 flex-wrap: nowrap;
 align-items: flex-start;
 word-break: break-word;
 line-height: var(--n-size);
 --n-merged-color-table: var(--n-color-table);
 `,[i(`show-label`,`line-height: var(--n-label-line-height);`),d(`&:hover`,[P(`checkbox-box`,[p(`border`,`border: var(--n-border-checked);`)])]),d(`&:focus:not(:active)`,[P(`checkbox-box`,[p(`border`,`
 border: var(--n-border-focus);
 box-shadow: var(--n-box-shadow-focus);
 `)])]),i(`inside-table`,[P(`checkbox-box`,`
 background-color: var(--n-merged-color-table);
 `)]),i(`checked`,[P(`checkbox-box`,`
 background-color: var(--n-color-checked);
 `,[P(`checkbox-icon`,[d(`.check-icon`,`
 opacity: 1;
 transform: scale(1);
 `)])])]),i(`indeterminate`,[P(`checkbox-box`,[P(`checkbox-icon`,[d(`.check-icon`,`
 opacity: 0;
 transform: scale(.5);
 `),d(`.line-icon`,`
 opacity: 1;
 transform: scale(1);
 `)])])]),i(`checked, indeterminate`,[d(`&:focus:not(:active)`,[P(`checkbox-box`,[p(`border`,`
 border: var(--n-border-checked);
 box-shadow: var(--n-box-shadow-focus);
 `)])]),P(`checkbox-box`,`
 background-color: var(--n-color-checked);
 border-left: 0;
 border-top: 0;
 `,[p(`border`,{border:`var(--n-border-checked)`})])]),i(`disabled`,{cursor:`not-allowed`},[i(`checked`,[P(`checkbox-box`,`
 background-color: var(--n-color-disabled-checked);
 `,[p(`border`,{border:`var(--n-border-disabled-checked)`}),P(`checkbox-icon`,[d(`.check-icon, .line-icon`,{fill:`var(--n-check-mark-color-disabled-checked)`})])])]),P(`checkbox-box`,`
 background-color: var(--n-color-disabled);
 `,[p(`border`,`
 border: var(--n-border-disabled);
 `),P(`checkbox-icon`,[d(`.check-icon, .line-icon`,`
 fill: var(--n-check-mark-color-disabled);
 `)])]),p(`label`,`
 color: var(--n-text-color-disabled);
 `)]),P(`checkbox-box-wrapper`,`
 position: relative;
 width: var(--n-size);
 flex-shrink: 0;
 flex-grow: 0;
 user-select: none;
 -webkit-user-select: none;
 `),P(`checkbox-box`,`
 position: absolute;
 left: 0;
 top: 50%;
 transform: translateY(-50%);
 height: var(--n-size);
 width: var(--n-size);
 display: inline-block;
 box-sizing: border-box;
 border-radius: var(--n-border-radius);
 background-color: var(--n-color);
 transition: background-color 0.3s var(--n-bezier);
 `,[p(`border`,`
 transition:
 border-color .3s var(--n-bezier),
 box-shadow .3s var(--n-bezier);
 border-radius: inherit;
 position: absolute;
 left: 0;
 right: 0;
 top: 0;
 bottom: 0;
 border: var(--n-border);
 `),P(`checkbox-icon`,`
 display: flex;
 align-items: center;
 justify-content: center;
 position: absolute;
 left: 1px;
 right: 1px;
 top: 1px;
 bottom: 1px;
 `,[d(`.check-icon, .line-icon`,`
 width: 100%;
 fill: var(--n-check-mark-color);
 opacity: 0;
 transform: scale(0.5);
 transform-origin: center;
 transition:
 fill 0.3s var(--n-bezier),
 transform 0.3s var(--n-bezier),
 opacity 0.3s var(--n-bezier),
 border-color 0.3s var(--n-bezier);
 `),N({left:`1px`,top:`1px`})])]),p(`label`,`
 color: var(--n-text-color);
 transition: color .3s var(--n-bezier);
 user-select: none;
 -webkit-user-select: none;
 padding: var(--n-label-padding);
 font-weight: var(--n-label-font-weight);
 `,[d(`&:empty`,{display:`none`})])]),r(P(`checkbox`,`
 --n-merged-color-table: var(--n-color-table-modal);
 `)),o(P(`checkbox`,`
 --n-merged-color-table: var(--n-color-table-popover);
 `))]),V=[`id`],H=[`tabindex`,`aria-checked`,`aria-labelledby`,`onKeyup`,`onKeydown`,`onClick`],U={...s.props,size:String,checked:{type:[Boolean,String,Number],default:void 0},defaultChecked:{type:[Boolean,String,Number],default:!1},value:[String,Number],disabled:{type:Boolean,default:void 0},indeterminate:Boolean,label:String,focusable:{type:Boolean,default:!0},checkedValue:{type:[Boolean,String,Number],default:!0},uncheckedValue:{type:[Boolean,String,Number],default:!1},"onUpdate:checked":[Function,Array],onUpdateChecked:[Function,Array],privateInsideTable:Boolean,onChange:[Function,Array]},W=S({name:`Checkbox`,props:U,setup(e){let n=y(G,null),r=k(null),{mergedClsPrefixRef:i,inlineThemeDisabled:a,mergedRtlRef:o,mergedComponentPropsRef:l}=D(e),d=k(e.defaultChecked),p=h(e,`checked`),g=I(p,d),_=c(()=>{if(n){let t=n.valueSetRef.value;return t&&e.value!==void 0?t.has(e.value):!1}return g.value===e.checkedValue}),v=f(e,{mergedSize(t){let{size:r}=e;if(r!==void 0)return r;if(n){let{value:e}=n.mergedSizeRef;if(e!==void 0)return e}if(t){let{mergedSize:e}=t;if(e!==void 0)return e.value}return l?.value?.Checkbox?.size||`medium`},mergedDisabled(t){let{disabled:r}=e;if(r!==void 0)return r;if(n){if(n.disabledRef.value)return!0;let{maxRef:{value:e},checkedCountRef:t}=n;if(e!==void 0&&t.value>=e&&!_.value)return!0;let{minRef:{value:r}}=n;if(r!==void 0&&t.value<=r&&_.value)return!0}return t?t.disabled.value:!1}}),{mergedDisabledRef:b,mergedSizeRef:x}=v,S=s(`Checkbox`,`-checkbox`,B,L,e,i);function C(r){if(n&&e.value!==void 0)n.toggleCheckbox(!_.value,e.value);else{let{onChange:n,"onUpdate:checked":i,onUpdateChecked:a}=e,{nTriggerFormInput:o,nTriggerFormChange:s}=v,c=_.value?e.uncheckedValue:e.checkedValue;i&&t(i,c,r),a&&t(a,c,r),n&&t(n,c,r),o(),s(),d.value=c}}function w(e){b.value||C(e)}function T(e){if(!b.value)switch(e.key){case` `:case`Enter`:C(e)}}function E(e){e.key===` `&&e.preventDefault()}let O={focus:()=>{r.value?.focus()},blur:()=>{r.value?.blur()}},A=M(`Checkbox`,o,i),N=j(()=>{let{value:e}=x,{common:{cubicBezierEaseInOut:t},self:{borderRadius:n,color:r,colorChecked:i,colorDisabled:a,colorTableHeader:o,colorTableHeaderModal:s,colorTableHeaderPopover:c,checkMarkColor:l,checkMarkColorDisabled:u,border:d,borderFocus:f,borderDisabled:p,borderChecked:h,boxShadowFocus:g,textColor:_,textColorDisabled:v,checkMarkColorDisabledChecked:y,colorDisabledChecked:b,borderDisabledChecked:C,labelPadding:w,labelLineHeight:T,labelFontWeight:E,[m(`fontSize`,e)]:D,[m(`size`,e)]:O}}=S.value;return{"--n-label-line-height":T,"--n-label-font-weight":E,"--n-size":O,"--n-bezier":t,"--n-border-radius":n,"--n-border":d,"--n-border-checked":h,"--n-border-focus":f,"--n-border-disabled":p,"--n-border-disabled-checked":C,"--n-box-shadow-focus":g,"--n-color":r,"--n-color-checked":i,"--n-color-table":o,"--n-color-table-modal":s,"--n-color-table-popover":c,"--n-color-disabled":a,"--n-color-disabled-checked":b,"--n-text-color":_,"--n-text-color-disabled":v,"--n-check-mark-color":l,"--n-check-mark-color-disabled":u,"--n-check-mark-color-disabled-checked":y,"--n-font-size":D,"--n-label-padding":w}}),P=a?u(`checkbox`,j(()=>x.value[0]),N,e):void 0;return Object.assign(v,O,{rtlEnabled:A,selfRef:r,mergedClsPrefix:i,mergedDisabled:b,renderedChecked:_,mergedTheme:S,labelId:F(),handleClick:w,handleKeyUp:T,handleKeyDown:E,cssVars:a?void 0:N,themeClass:P?.themeClass,onRender:P?.onRender})},render(){let{$slots:t,renderedChecked:n,mergedDisabled:r,indeterminate:i,privateInsideTable:o,cssVars:s,labelId:c,label:u,mergedClsPrefix:d,focusable:f,handleKeyUp:p,handleKeyDown:m,handleClick:h}=this;this.onRender?.();let _=w(t.default,e=>u||e?(T(),x(`span`,{key:1,class:a(`${d}-checkbox__label`),id:c},[g(()=>u||e)],10,V)):null);return(()=>{let t=O(`70be6e74cd27cb50`);return T(),x(`div`,{ref:`selfRef`,class:a([`${d}-checkbox`,this.themeClass,this.rtlEnabled&&`${d}-checkbox--rtl`,n&&`${d}-checkbox--checked`,r&&`${d}-checkbox--disabled`,i&&`${d}-checkbox--indeterminate`,o&&`${d}-checkbox--inside-table`,_&&`${d}-checkbox--show-label`]),tabindex:r||!f?void 0:0,role:`checkbox`,"aria-checked":i?`mixed`:n,"aria-labelledby":c,style:e(s),onKeyup:p,onKeydown:m,onClick:h,onMousedown:t[0]||=()=>{l(`selectstart`,window,e=>{e.preventDefault()},{once:!0})}},[b(`div`,{class:a(`${d}-checkbox-box-wrapper`)},[t[1]||=g(`\xA0`,-1),b(`div`,{class:a(`${d}-checkbox-box`)},[C(v,null,{default:()=>this.indeterminate?(T(),x(`div`,{key:`indeterminate`,class:a(`${d}-checkbox-icon`)},[g(()=>z())],2)):(T(),x(`div`,{key:`check`,class:a(`${d}-checkbox-icon`)},[g(()=>R())],2))},1024),b(`div`,{class:a(`${d}-checkbox-box__border`)},null,2)],2)],2),g(()=>_)],46,H)})()}}),G=_(`n-checkbox-group`),K=S({name:`CheckboxGroup`,props:{min:Number,max:Number,size:String,options:Array,labelField:{type:String,default:`label`},valueField:{type:String,default:`value`},value:Array,defaultValue:{type:Array,default:null},disabled:{type:Boolean,default:void 0},"onUpdate:value":[Function,Array],onUpdateValue:[Function,Array],onChange:[Function,Array]},setup(e){let{mergedClsPrefixRef:r}=D(e),i=f(e),{mergedSizeRef:a,mergedDisabledRef:o}=i,s=k(e.defaultValue),c=j(()=>e.value),l=I(c,s),u=j(()=>l.value?.length||0),d=j(()=>Array.isArray(l.value)?new Set(l.value):new Set);function p(n,r){let{nTriggerFormInput:a,nTriggerFormChange:o}=i,{onChange:c,"onUpdate:value":u,onUpdateValue:d}=e;if(Array.isArray(l.value)){let e=Array.from(l.value),i=e.findIndex(e=>e===r);n?~i||(e.push(r),d&&t(d,e,{actionType:`check`,value:r}),u&&t(u,e,{actionType:`check`,value:r}),a(),o(),s.value=e,c&&t(c,e)):~i&&(e.splice(i,1),d&&t(d,e,{actionType:`uncheck`,value:r}),u&&t(u,e,{actionType:`uncheck`,value:r}),c&&t(c,e),s.value=e,a(),o())}else n?(d&&t(d,[r],{actionType:`check`,value:r}),u&&t(u,[r],{actionType:`check`,value:r}),c&&t(c,[r]),s.value=[r],a(),o()):(d&&t(d,[],{actionType:`uncheck`,value:r}),u&&t(u,[],{actionType:`uncheck`,value:r}),c&&t(c,[]),s.value=[],a(),o())}return n(G,{checkedCountRef:u,maxRef:h(e,`max`),minRef:h(e,`min`),valueSetRef:d,disabledRef:o,mergedSizeRef:a,toggleCheckbox:p}),{mergedClsPrefix:r}},render(){let{options:e,labelField:t,valueField:n}=this.$props;return T(),x(`div`,{class:a(`${this.mergedClsPrefix}-checkbox-group`),role:`group`},[e?(T(),x(A,{key:0},[g(()=>e.map(e=>{let r=e[n];return T(),E(W,{key:r,value:r,disabled:e.disabled,label:e[t]},null,8,[`value`,`disabled`,`label`])}))],64)):(T(),x(A,{key:1},[g(()=>this.$slots.default?.())],64))],2)}});export{W as n,K as t};