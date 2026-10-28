import{B as e,Et as t,F as n,Fn as r,Ht as i,Kt as a,Lt as o,M as s,S as c,St as l,T as u,Tt as d,U as f,Ut as p,Wt as m,Xt as h,Zt as g,b as _,d as v,dn as y,fn as b,j as x,jn as S,kn as C,m as w,p as T,tn as E,u as D,vt as O,w as k,wt as A,xt as j,y as M,yt as N}from"./vue-router-DEBuQMrJ.js";import{p as P}from"./client-Cn9-q7d8.js";import{t as F}from"./misc-DDs3MKLt.js";import{t as I}from"./use-merged-state-C_DmUKj7.js";import{j as L}from"./index-CCNV-6PF.js";var R=()=>(()=>{let e=x(`75be776d8875fa17`);return e[0]||=p(`svg`,{viewBox:`0 0 64 64`,class:`check-icon`},[p(`path`,{d:`M50.42,16.76L22.34,39.45l-8.1-11.46c-1.12-1.58-3.3-1.96-4.88-0.84c-1.58,1.12-1.95,3.3-0.84,4.88l10.26,14.51  c0.56,0.79,1.42,1.31,2.38,1.45c0.16,0.02,0.32,0.03,0.48,0.03c0.8,0,1.57-0.27,2.2-0.78l30.99-25.03c1.5-1.21,1.74-3.42,0.52-4.92  C54.13,15.78,51.93,15.55,50.42,16.76z`})],-1)})(),z=()=>(()=>{let e=x(`c6eed899356c8404`);return e[0]||=p(`svg`,{viewBox:`0 0 100 100`,class:`line-icon`},[p(`path`,{d:`M80.2,55.5H21.4c-2.8,0-5.1-2.5-5.1-5.5l0,0c0-3,2.3-5.5,5.1-5.5h58.7c2.8,0,5.1,2.5,5.1,5.5l0,0C85.2,53.1,82.9,55.5,80.2,55.5z`})],-1)})(),B=O([N(`checkbox`,`
 font-size: var(--n-font-size);
 outline: none;
 cursor: pointer;
 display: inline-flex;
 flex-wrap: nowrap;
 align-items: flex-start;
 word-break: break-word;
 line-height: var(--n-size);
 --n-merged-color-table: var(--n-color-table);
 `,[l(`show-label`,`line-height: var(--n-label-line-height);`),O(`&:hover`,[N(`checkbox-box`,[j(`border`,`border: var(--n-border-checked);`)])]),O(`&:focus:not(:active)`,[N(`checkbox-box`,[j(`border`,`
 border: var(--n-border-focus);
 box-shadow: var(--n-box-shadow-focus);
 `)])]),l(`inside-table`,[N(`checkbox-box`,`
 background-color: var(--n-merged-color-table);
 `)]),l(`checked`,[N(`checkbox-box`,`
 background-color: var(--n-color-checked);
 `,[N(`checkbox-icon`,[O(`.check-icon`,`
 opacity: 1;
 transform: scale(1);
 `)])])]),l(`indeterminate`,[N(`checkbox-box`,[N(`checkbox-icon`,[O(`.check-icon`,`
 opacity: 0;
 transform: scale(.5);
 `),O(`.line-icon`,`
 opacity: 1;
 transform: scale(1);
 `)])])]),l(`checked, indeterminate`,[O(`&:focus:not(:active)`,[N(`checkbox-box`,[j(`border`,`
 border: var(--n-border-checked);
 box-shadow: var(--n-box-shadow-focus);
 `)])]),N(`checkbox-box`,`
 background-color: var(--n-color-checked);
 border-left: 0;
 border-top: 0;
 `,[j(`border`,{border:`var(--n-border-checked)`})])]),l(`disabled`,{cursor:`not-allowed`},[l(`checked`,[N(`checkbox-box`,`
 background-color: var(--n-color-disabled-checked);
 `,[j(`border`,{border:`var(--n-border-disabled-checked)`}),N(`checkbox-icon`,[O(`.check-icon, .line-icon`,{fill:`var(--n-check-mark-color-disabled-checked)`})])])]),N(`checkbox-box`,`
 background-color: var(--n-color-disabled);
 `,[j(`border`,`
 border: var(--n-border-disabled);
 `),N(`checkbox-icon`,[O(`.check-icon, .line-icon`,`
 fill: var(--n-check-mark-color-disabled);
 `)])]),j(`label`,`
 color: var(--n-text-color-disabled);
 `)]),N(`checkbox-box-wrapper`,`
 position: relative;
 width: var(--n-size);
 flex-shrink: 0;
 flex-grow: 0;
 user-select: none;
 -webkit-user-select: none;
 `),N(`checkbox-box`,`
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
 `,[j(`border`,`
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
 `),N(`checkbox-icon`,`
 display: flex;
 align-items: center;
 justify-content: center;
 position: absolute;
 left: 1px;
 right: 1px;
 top: 1px;
 bottom: 1px;
 `,[O(`.check-icon, .line-icon`,`
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
 `),D({left:`1px`,top:`1px`})])]),j(`label`,`
 color: var(--n-text-color);
 transition: color .3s var(--n-bezier);
 user-select: none;
 -webkit-user-select: none;
 padding: var(--n-label-padding);
 font-weight: var(--n-label-font-weight);
 `,[O(`&:empty`,{display:`none`})])]),d(N(`checkbox`,`
 --n-merged-color-table: var(--n-color-table-modal);
 `)),t(N(`checkbox`,`
 --n-merged-color-table: var(--n-color-table-popover);
 `))]),V=[`id`],H=[`tabindex`,`aria-checked`,`aria-labelledby`,`onKeyup`,`onKeydown`,`onClick`],U={...k.props,size:String,checked:{type:[Boolean,String,Number],default:void 0},defaultChecked:{type:[Boolean,String,Number],default:!1},value:[String,Number],disabled:{type:Boolean,default:void 0},indeterminate:Boolean,label:String,focusable:{type:Boolean,default:!0},checkedValue:{type:[Boolean,String,Number],default:!0},uncheckedValue:{type:[Boolean,String,Number],default:!1},"onUpdate:checked":[Function,Array],onUpdateChecked:[Function,Array],privateInsideTable:Boolean,onChange:[Function,Array]},W=g({name:`Checkbox`,props:U,setup(t){let n=E(G,null),r=C(null),{mergedClsPrefixRef:a,inlineThemeDisabled:o,mergedRtlRef:s,mergedComponentPropsRef:l}=e(t),d=C(t.defaultChecked),f=S(t,`checked`),p=I(f,d),m=c(()=>{if(n){let e=n.valueSetRef.value;return e&&t.value!==void 0?e.has(t.value):!1}return p.value===t.checkedValue}),h=T(t,{mergedSize(e){let{size:r}=t;if(r!==void 0)return r;if(n){let{value:e}=n.mergedSizeRef;if(e!==void 0)return e}if(e){let{mergedSize:t}=e;if(t!==void 0)return t.value}return l?.value?.Checkbox?.size||`medium`},mergedDisabled(e){let{disabled:r}=t;if(r!==void 0)return r;if(n){if(n.disabledRef.value)return!0;let{maxRef:{value:e},checkedCountRef:t}=n;if(e!==void 0&&t.value>=e&&!m.value)return!0;let{minRef:{value:r}}=n;if(r!==void 0&&t.value<=r&&m.value)return!0}return e?e.disabled.value:!1}}),{mergedDisabledRef:g,mergedSizeRef:v}=h,y=k(`Checkbox`,`-checkbox`,B,L,t,a);function b(e){if(n&&t.value!==void 0)n.toggleCheckbox(!m.value,t.value);else{let{onChange:n,"onUpdate:checked":r,onUpdateChecked:i}=t,{nTriggerFormInput:a,nTriggerFormChange:o}=h,s=m.value?t.uncheckedValue:t.checkedValue;r&&_(r,s,e),i&&_(i,s,e),n&&_(n,s,e),a(),o(),d.value=s}}function x(e){g.value||b(e)}function D(e){if(!g.value)switch(e.key){case` `:case`Enter`:b(e)}}function O(e){e.key===` `&&e.preventDefault()}let j={focus:()=>{r.value?.focus()},blur:()=>{r.value?.blur()}},M=w(`Checkbox`,s,a),N=i(()=>{let{value:e}=v,{common:{cubicBezierEaseInOut:t},self:{borderRadius:n,color:r,colorChecked:i,colorDisabled:a,colorTableHeader:o,colorTableHeaderModal:s,colorTableHeaderPopover:c,checkMarkColor:l,checkMarkColorDisabled:u,border:d,borderFocus:f,borderDisabled:p,borderChecked:m,boxShadowFocus:h,textColor:g,textColorDisabled:_,checkMarkColorDisabledChecked:b,colorDisabledChecked:x,borderDisabledChecked:S,labelPadding:C,labelLineHeight:w,labelFontWeight:T,[A(`fontSize`,e)]:E,[A(`size`,e)]:D}}=y.value;return{"--n-label-line-height":w,"--n-label-font-weight":T,"--n-size":D,"--n-bezier":t,"--n-border-radius":n,"--n-border":d,"--n-border-checked":m,"--n-border-focus":f,"--n-border-disabled":p,"--n-border-disabled-checked":S,"--n-box-shadow-focus":h,"--n-color":r,"--n-color-checked":i,"--n-color-table":o,"--n-color-table-modal":s,"--n-color-table-popover":c,"--n-color-disabled":a,"--n-color-disabled-checked":x,"--n-text-color":g,"--n-text-color-disabled":_,"--n-check-mark-color":l,"--n-check-mark-color-disabled":u,"--n-check-mark-color-disabled-checked":b,"--n-font-size":E,"--n-label-padding":C}}),P=o?u(`checkbox`,i(()=>v.value[0]),N,t):void 0;return Object.assign(h,j,{rtlEnabled:M,selfRef:r,mergedClsPrefix:a,mergedDisabled:g,renderedChecked:m,mergedTheme:y,labelId:F(),handleClick:x,handleKeyUp:D,handleKeyDown:O,cssVars:o?void 0:N,themeClass:P?.themeClass,onRender:P?.onRender})},render(){let{$slots:e,renderedChecked:t,mergedDisabled:i,indeterminate:o,privateInsideTable:c,cssVars:l,labelId:u,label:d,mergedClsPrefix:f,focusable:m,handleKeyUp:g,handleKeyDown:_,handleClick:b}=this;this.onRender?.();let S=M(e.default,e=>d||e?(y(),a(`span`,{key:1,class:s(`${f}-checkbox__label`),id:u},[n(()=>d||e)],10,V)):null);return(()=>{let e=x(`70be6e74cd27cb50`);return y(),a(`div`,{ref:`selfRef`,class:s([`${f}-checkbox`,this.themeClass,this.rtlEnabled&&`${f}-checkbox--rtl`,t&&`${f}-checkbox--checked`,i&&`${f}-checkbox--disabled`,o&&`${f}-checkbox--indeterminate`,c&&`${f}-checkbox--inside-table`,S&&`${f}-checkbox--show-label`]),tabindex:i||!m?void 0:0,role:`checkbox`,"aria-checked":o?`mixed`:t,"aria-labelledby":u,style:r(l),onKeyup:g,onKeydown:_,onClick:b,onMousedown:e[0]||=()=>{P(`selectstart`,window,e=>{e.preventDefault()},{once:!0})}},[p(`div`,{class:s(`${f}-checkbox-box-wrapper`)},[e[1]||=n(`\xA0`,-1),p(`div`,{class:s(`${f}-checkbox-box`)},[h(v,null,{default:()=>this.indeterminate?(y(),a(`div`,{key:`indeterminate`,class:s(`${f}-checkbox-icon`)},[n(()=>z())],2)):(y(),a(`div`,{key:`check`,class:s(`${f}-checkbox-icon`)},[n(()=>R())],2))},1024),p(`div`,{class:s(`${f}-checkbox-box__border`)},null,2)],2)],2),n(()=>S)],46,H)})()}}),G=f(`n-checkbox-group`),K=g({name:`CheckboxGroup`,props:{min:Number,max:Number,size:String,options:Array,labelField:{type:String,default:`label`},valueField:{type:String,default:`value`},value:Array,defaultValue:{type:Array,default:null},disabled:{type:Boolean,default:void 0},"onUpdate:value":[Function,Array],onUpdateValue:[Function,Array],onChange:[Function,Array]},setup(t){let{mergedClsPrefixRef:n}=e(t),r=T(t),{mergedSizeRef:a,mergedDisabledRef:o}=r,s=C(t.defaultValue),c=i(()=>t.value),l=I(c,s),u=i(()=>l.value?.length||0),d=i(()=>Array.isArray(l.value)?new Set(l.value):new Set);function f(e,n){let{nTriggerFormInput:i,nTriggerFormChange:a}=r,{onChange:o,"onUpdate:value":c,onUpdateValue:u}=t;if(Array.isArray(l.value)){let t=Array.from(l.value),r=t.findIndex(e=>e===n);e?~r||(t.push(n),u&&_(u,t,{actionType:`check`,value:n}),c&&_(c,t,{actionType:`check`,value:n}),i(),a(),s.value=t,o&&_(o,t)):~r&&(t.splice(r,1),u&&_(u,t,{actionType:`uncheck`,value:n}),c&&_(c,t,{actionType:`uncheck`,value:n}),o&&_(o,t),s.value=t,i(),a())}else e?(u&&_(u,[n],{actionType:`check`,value:n}),c&&_(c,[n],{actionType:`check`,value:n}),o&&_(o,[n]),s.value=[n],i(),a()):(u&&_(u,[],{actionType:`uncheck`,value:n}),c&&_(c,[],{actionType:`uncheck`,value:n}),o&&_(o,[]),s.value=[],i(),a())}return b(G,{checkedCountRef:u,maxRef:S(t,`max`),minRef:S(t,`min`),valueSetRef:d,disabledRef:o,mergedSizeRef:a,toggleCheckbox:f}),{mergedClsPrefix:n}},render(){let{options:e,labelField:t,valueField:r}=this.$props;return y(),a(`div`,{class:s(`${this.mergedClsPrefix}-checkbox-group`),role:`group`},[e?(y(),a(o,{key:0},[n(()=>e.map(e=>{let n=e[r];return y(),m(W,{key:n,value:n,disabled:e.disabled,label:e[t]},null,8,[`value`,`disabled`,`label`])}))],64)):(y(),a(o,{key:1},[n(()=>this.$slots.default?.())],64))],2)}});export{W as n,K as t};