import{$n as e,A as t,An as n,Dn as r,Fn as i,Ht as a,J as o,L as s,M as c,Qt as l,R as u,Rn as d,Rt as f,S as p,Sn as m,Ut as h,Vt as g,Wt as _,Yn as v,Z as y,Zn as b,at as x,bn as S,cn as C,d as w,dn as T,er as E,gn as D,hn as O,in as ee,jn as te,k,kn as A,ln as j,mn as M,nt as N,q as ne,qn as P,rn as F,s as re,sn as I,tn as L,un as R,w as z,zt as B}from"./vue-router-CtlYBEfb.js";import{t as V}from"./_plugin-vue_export-helper-BVU0-94s.js";import{t as H}from"./use-merged-state-vBUfWV25.js";import{t as ie}from"./Input-Cpd-NjAr.js";import{t as ae}from"./use-message-HCkHApIe.js";import{a as oe,rt as se,y as U}from"./index-1sxyyN4B.js";import{t as W}from"./createLucideIcon-E2g0wvUY.js";import{t as G}from"./x-n2es1joo.js";var K=B(`radio`,`
 line-height: var(--n-label-line-height);
 outline: none;
 position: relative;
 user-select: none;
 -webkit-user-select: none;
 display: inline-flex;
 align-items: flex-start;
 flex-wrap: nowrap;
 font-size: var(--n-font-size);
 word-break: break-word;
`,[a(`checked`,[g(`dot`,`
 background-color: var(--n-color-active);
 `)]),g(`dot-wrapper`,`
 position: relative;
 flex-shrink: 0;
 flex-grow: 0;
 width: var(--n-radio-size);
 `),B(`radio-input`,`
 position: absolute;
 border: 0;
 width: 0;
 height: 0;
 opacity: 0;
 margin: 0;
 `),g(`dot`,`
 position: absolute;
 top: 50%;
 left: 0;
 transform: translateY(-50%);
 height: var(--n-radio-size);
 width: var(--n-radio-size);
 background: var(--n-color);
 box-shadow: var(--n-box-shadow);
 border-radius: 50%;
 transition:
 background-color .3s var(--n-bezier),
 box-shadow .3s var(--n-bezier);
 `,[f(`&::before`,`
 content: "";
 opacity: 0;
 position: absolute;
 left: 4px;
 top: 4px;
 height: calc(100% - 8px);
 width: calc(100% - 8px);
 border-radius: 50%;
 transform: scale(.8);
 background: var(--n-dot-color-active);
 transition: 
 opacity .3s var(--n-bezier),
 background-color .3s var(--n-bezier),
 transform .3s var(--n-bezier);
 `),a(`checked`,{boxShadow:`var(--n-box-shadow-active)`},[f(`&::before`,`
 opacity: 1;
 transform: scale(1);
 `)])]),g(`label`,`
 color: var(--n-text-color);
 padding: var(--n-label-padding);
 font-weight: var(--n-label-font-weight);
 display: inline-block;
 transition: color .3s var(--n-bezier);
 `),h(`disabled`,`
 cursor: pointer;
 `,[f(`&:hover`,[g(`dot`,{boxShadow:`var(--n-box-shadow-hover)`})]),a(`focus`,[f(`&:not(:active)`,[g(`dot`,{boxShadow:`var(--n-box-shadow-focus)`})])])]),a(`disabled`,`
 cursor: not-allowed;
 `,[g(`dot`,{boxShadow:`var(--n-box-shadow-disabled)`,backgroundColor:`var(--n-color-disabled)`},[f(`&::before`,{backgroundColor:`var(--n-dot-color-disabled)`}),a(`checked`,`
 opacity: 1;
 `)]),g(`label`,{color:`var(--n-text-color-disabled)`}),B(`radio-input`,`
 cursor: not-allowed;
 `)])]),q={name:String,value:{type:[String,Number,Boolean],default:`on`},checked:{type:Boolean,default:void 0},defaultChecked:Boolean,disabled:{type:Boolean,default:void 0},label:String,size:String,onUpdateChecked:[Function,Array],"onUpdate:checked":[Function,Array],checkedValue:{type:Boolean,default:void 0}},J=x(`n-radio-group`);function Y(e){let n=S(J,null),{mergedClsPrefixRef:r,mergedComponentPropsRef:i}=N(e),a=p(e,{mergedSize(t){let{size:r}=e;if(r!==void 0)return r;if(n){let{mergedSizeRef:{value:e}}=n;if(e!==void 0)return e}return t?t.mergedSize.value:i?.value?.Radio?.size||`medium`},mergedDisabled(t){return!!(e.disabled||n?.disabledRef.value||t?.disabled.value)}}),{mergedSizeRef:o,mergedDisabledRef:s}=a,l=P(null),u=P(null),d=P(e.defaultChecked),f=v(e,`checked`),m=H(f,d),h=c(()=>n?n.valueRef.value===e.value:m.value),g=c(()=>{let{name:t}=e;if(t!==void 0)return t;if(n)return n.nameRef.value}),_=P(!1);function y(){if(n){let{doUpdateValue:r}=n,{value:i}=e;t(r,i)}else{let{onUpdateChecked:n,"onUpdate:checked":r}=e,{nTriggerFormInput:i,nTriggerFormChange:o}=a;n&&t(n,!0),r&&t(r,!0),i(),o(),d.value=!0}}function b(){s.value||h.value||y()}function x(){b(),l.value&&(l.value.checked=h.value)}function C(){_.value=!1}function w(){_.value=!0}return{mergedClsPrefix:n?n.mergedClsPrefixRef:r,inputRef:l,labelRef:u,mergedName:g,mergedDisabled:s,renderSafeChecked:h,focus:_,mergedSize:o,handleRadioInputChange:x,handleRadioInputBlur:C,handleRadioInputFocus:w}}var ce=[`value`,`name`,`checked`,`disabled`,`onChange`,`onFocus`,`onBlur`],X={...s.props,...q},Z=D({name:`Radio`,props:X,setup(e){let t=Y(e),n=s(`Radio`,`-radio`,K,U,e,t.mergedClsPrefix),r=I(()=>{let{mergedSize:{value:e}}=t,{common:{cubicBezierEaseInOut:r},self:{boxShadow:i,boxShadowActive:a,boxShadowDisabled:o,boxShadowFocus:s,boxShadowHover:c,color:l,colorDisabled:u,colorActive:d,textColor:f,textColorDisabled:p,dotColorActive:m,dotColorDisabled:h,labelPadding:g,labelLineHeight:v,labelFontWeight:y,[_(`fontSize`,e)]:b,[_(`radioSize`,e)]:x}}=n.value;return{"--n-bezier":r,"--n-label-line-height":v,"--n-label-font-weight":y,"--n-box-shadow":i,"--n-box-shadow-active":a,"--n-box-shadow-disabled":o,"--n-box-shadow-focus":s,"--n-box-shadow-hover":c,"--n-color":l,"--n-color-active":d,"--n-color-disabled":u,"--n-dot-color-active":m,"--n-dot-color-disabled":h,"--n-font-size":b,"--n-radio-size":x,"--n-text-color":f,"--n-text-color-disabled":p,"--n-label-padding":g}}),{inlineThemeDisabled:i,mergedClsPrefixRef:a,mergedRtlRef:o}=N(e),c=z(`Radio`,o,a),l=i?u(`radio`,I(()=>t.mergedSize.value[0]),r,e):void 0;return Object.assign(t,{rtlEnabled:c,cssVars:i?void 0:r,themeClass:l?.themeClass,onRender:l?.onRender})},render(){let{$slots:t,mergedClsPrefix:n,onRender:r,label:i}=this;return r?.(),(()=>{let r=ne(`f8c6901d8cd45c02`);return A(),T(`label`,{class:o([`${n}-radio`,this.themeClass,this.rtlEnabled&&`${n}-radio--rtl`,this.mergedDisabled&&`${n}-radio--disabled`,this.renderSafeChecked&&`${n}-radio--checked`,this.focus&&`${n}-radio--focus`]),style:e(this.cssVars)},[C(`div`,{class:o(`${n}-radio__dot-wrapper`)},[r[0]||=y(`\xA0`,-1),C(`div`,{class:o([`${n}-radio__dot`,this.renderSafeChecked&&`${n}-radio__dot--checked`])},null,2),C(`input`,{ref:`inputRef`,type:`radio`,class:o(`${n}-radio-input`),value:this.value,name:this.mergedName,checked:this.renderSafeChecked,disabled:this.mergedDisabled,onChange:this.handleRadioInputChange,onFocus:this.handleRadioInputFocus,onBlur:this.handleRadioInputBlur},null,42,ce)],2),y(()=>k(t.default,e=>!e&&!i?null:(A(),T(`div`,{ref:`labelRef`,class:o(`${n}-radio__label`)},[y(()=>e||i)],2))))],6)})()}}),le=[`value`,`name`,`checked`,`disabled`,`onChange`,`onFocus`,`onBlur`],ue=D({name:`RadioButton`,props:q,setup:Y,render(){let{mergedClsPrefix:e}=this;return A(),T(`label`,{class:o([`${e}-radio-button`,this.mergedDisabled&&`${e}-radio-button--disabled`,this.renderSafeChecked&&`${e}-radio-button--checked`,this.focus&&[`${e}-radio-button--focus`]])},[C(`input`,{ref:`inputRef`,type:`radio`,class:o(`${e}-radio-input`),value:this.value,name:this.mergedName,checked:this.renderSafeChecked,disabled:this.mergedDisabled,onChange:this.handleRadioInputChange,onFocus:this.handleRadioInputFocus,onBlur:this.handleRadioInputBlur},null,42,le),C(`div`,{class:o(`${e}-radio-button__state-border`)},null,2),y(()=>k(this.$slots.default,t=>!t&&!this.label?null:(A(),T(`div`,{ref:`labelRef`,class:o(`${e}-radio__label`)},[y(()=>t||this.label)],2))))],2)}});function de(e,t=`default`,n=[]){let r=e.$slots[t];return r===void 0?n:r()}var fe=B(`radio-group`,`
 display: inline-block;
 font-size: var(--n-font-size);
`,[g(`splitor`,`
 display: inline-block;
 vertical-align: bottom;
 width: 1px;
 transition:
 background-color .3s var(--n-bezier),
 opacity .3s var(--n-bezier);
 background: var(--n-button-border-color);
 `,[a(`checked`,{backgroundColor:`var(--n-button-border-color-active)`}),a(`disabled`,{opacity:`var(--n-opacity-disabled)`})]),a(`button-group`,`
 white-space: nowrap;
 height: var(--n-height);
 line-height: var(--n-height);
 `,[B(`radio-button`,{height:`var(--n-height)`,lineHeight:`var(--n-height)`}),g(`splitor`,{height:`var(--n-height)`})]),B(`radio-button`,`
 vertical-align: bottom;
 outline: none;
 position: relative;
 user-select: none;
 -webkit-user-select: none;
 display: inline-block;
 box-sizing: border-box;
 padding-left: 14px;
 padding-right: 14px;
 white-space: nowrap;
 transition:
 background-color .3s var(--n-bezier),
 opacity .3s var(--n-bezier),
 border-color .3s var(--n-bezier),
 color .3s var(--n-bezier);
 background: var(--n-button-color);
 color: var(--n-button-text-color);
 border-top: 1px solid var(--n-button-border-color);
 border-bottom: 1px solid var(--n-button-border-color);
 `,[B(`radio-input`,`
 pointer-events: none;
 position: absolute;
 border: 0;
 border-radius: inherit;
 left: 0;
 right: 0;
 top: 0;
 bottom: 0;
 opacity: 0;
 z-index: 1;
 `),g(`state-border`,`
 z-index: 1;
 pointer-events: none;
 position: absolute;
 box-shadow: var(--n-button-box-shadow);
 transition: box-shadow .3s var(--n-bezier);
 left: -1px;
 bottom: -1px;
 right: -1px;
 top: -1px;
 `),f(`&:first-child`,`
 border-top-left-radius: var(--n-button-border-radius);
 border-bottom-left-radius: var(--n-button-border-radius);
 border-left: 1px solid var(--n-button-border-color);
 `,[g(`state-border`,`
 border-top-left-radius: var(--n-button-border-radius);
 border-bottom-left-radius: var(--n-button-border-radius);
 `)]),f(`&:last-child`,`
 border-top-right-radius: var(--n-button-border-radius);
 border-bottom-right-radius: var(--n-button-border-radius);
 border-right: 1px solid var(--n-button-border-color);
 `,[g(`state-border`,`
 border-top-right-radius: var(--n-button-border-radius);
 border-bottom-right-radius: var(--n-button-border-radius);
 `)]),h(`disabled`,`
 cursor: pointer;
 `,[f(`&:hover`,[g(`state-border`,`
 transition: box-shadow .3s var(--n-bezier);
 box-shadow: var(--n-button-box-shadow-hover);
 `),h(`checked`,{color:`var(--n-button-text-color-hover)`})]),a(`focus`,[f(`&:not(:active)`,[g(`state-border`,{boxShadow:`var(--n-button-box-shadow-focus)`})])])]),a(`checked`,`
 background: var(--n-button-color-active);
 color: var(--n-button-text-color-active);
 border-color: var(--n-button-border-color-active);
 `),a(`disabled`,`
 cursor: not-allowed;
 opacity: var(--n-opacity-disabled);
 `)])]),pe=[`onFocusin`,`onFocusout`];function me(e,t,n){let r=[],i=!1;for(let a=0;a<e.length;++a){let s=e[a],c=s.type?.name;c===`RadioButton`&&(i=!0);let l=s.props;if(c!==`RadioButton`){r.push(s);continue}if(a===0)r.push(s);else{let e=r[r.length-1].props,i=t===e.value,a=e.disabled,c=t===l.value,u=l.disabled,d=(i?2:0)+ +!a,f=(c?2:0)+ +!u,p={[`${n}-radio-group__splitor--disabled`]:a,[`${n}-radio-group__splitor--checked`]:i},m={[`${n}-radio-group__splitor--disabled`]:u,[`${n}-radio-group__splitor--checked`]:c},h=d<f?m:p;r.push((A(),T(`div`,{key:1,class:o([`${n}-radio-group__splitor`,h])},null,2)),s)}}return{children:r,isButtonGroup:i}}var he={...s.props,name:String,options:Array,labelField:{type:String,default:`label`},valueField:{type:String,default:`value`},value:[String,Number,Boolean],defaultValue:{type:[String,Number,Boolean],default:null},size:String,disabled:{type:Boolean,default:void 0},"onUpdate:value":[Function,Array],onUpdateValue:[Function,Array]},ge=D({name:`RadioGroup`,props:he,setup(e){let r=P(null),{mergedSizeRef:i,mergedDisabledRef:a,nTriggerFormChange:o,nTriggerFormInput:c,nTriggerFormBlur:l,nTriggerFormFocus:d}=p(e),{mergedClsPrefixRef:f,inlineThemeDisabled:m,mergedRtlRef:h}=N(e),g=s(`Radio`,`-radio-group`,fe,U,e,f),y=P(e.defaultValue),b=v(e,`value`),x=H(b,y);function S(n){let{onUpdateValue:r,"onUpdate:value":i}=e;r&&t(r,n),i&&t(i,n),y.value=n,o(),c()}function C(e){let{value:t}=r;t&&(t.contains(e.relatedTarget)||d())}function w(e){let{value:t}=r;t&&(t.contains(e.relatedTarget)||l())}n(J,{mergedClsPrefixRef:f,nameRef:v(e,`name`),valueRef:x,disabledRef:a,mergedSizeRef:i,doUpdateValue:S});let T=z(`Radio`,h,f),E=I(()=>{let{value:e}=i,{common:{cubicBezierEaseInOut:t},self:{buttonBorderColor:n,buttonBorderColorActive:r,buttonBorderRadius:a,buttonBoxShadow:o,buttonBoxShadowFocus:s,buttonBoxShadowHover:c,buttonColor:l,buttonColorActive:u,buttonTextColor:d,buttonTextColorActive:f,buttonTextColorHover:p,opacityDisabled:m,[_(`buttonHeight`,e)]:h,[_(`fontSize`,e)]:v}}=g.value;return{"--n-font-size":v,"--n-bezier":t,"--n-button-border-color":n,"--n-button-border-color-active":r,"--n-button-border-radius":a,"--n-button-box-shadow":o,"--n-button-box-shadow-focus":s,"--n-button-box-shadow-hover":c,"--n-button-color":l,"--n-button-color-active":u,"--n-button-text-color":d,"--n-button-text-color-hover":p,"--n-button-text-color-active":f,"--n-height":h,"--n-opacity-disabled":m}}),D=m?u(`radio-group`,I(()=>i.value[0]),E,e):void 0;return{selfElRef:r,rtlEnabled:T,mergedClsPrefix:f,mergedValue:x,handleFocusout:w,handleFocusin:C,cssVars:m?void 0:E,themeClass:D?.themeClass,onRender:D?.onRender}},render(){let{mergedValue:t,mergedClsPrefix:n,handleFocusin:r,handleFocusout:i}=this,{options:a,labelField:s,valueField:c}=this.$props,{children:l,isButtonGroup:u}=me(a?a.map(e=>{let t=e[c];return A(),j(Z,{key:typeof t==`boolean`?`__n_${t}`:t,value:t,disabled:e.disabled,label:e[s]},null,8,[`value`,`disabled`,`label`])}):se(de(this)),t,n);return this.onRender?.(),A(),T(`div`,{onFocusin:r,onFocusout:i,ref:`selfElRef`,class:o([`${n}-radio-group`,this.rtlEnabled&&`${n}-radio-group--rtl`,this.themeClass,u&&`${n}-radio-group--button-group`]),style:e(this.cssVars)},[y(()=>l)],46,pe)}}),_e=W(`folder-open`,[[`path`,{d:`m6 14 1.5-2.9A2 2 0 0 1 9.24 10H20a2 2 0 0 1 1.94 2.5l-1.54 6a2 2 0 0 1-1.95 1.5H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h3.9a2 2 0 0 1 1.69.9l.81 1.2a2 2 0 0 0 1.67.9H18a2 2 0 0 1 2 2v2`,key:`usdka0`}]]),ve=`https://a.favicon.im/`;function Q(e){let t=(e??``).trim();return t?t.startsWith(`/`)||/^(https?:)\/\//i.test(t)?t:ve+t:``}function $(e,t){let n=e().trim();if(!n)return;let r=Q(n);r!==n&&t(r)}function ye(e){return(e??``).trim().slice(0,1).toUpperCase()}var be={class:`logo-pick`},xe=[`src`],Se={key:1,class:`pick-empty pick-error`},Ce={key:2,class:`pick-empty`},we={class:`pick-side`},Te=V(D({__name:`LogoPicker`,props:{existing:{},existingKind:{},libraryUrl:{}},emits:[`change`,`library`],setup(e,{expose:t,emit:n}){let r=e,a=n,o=ae(),s=oe(),c=P(``),l=P(null),u=P(``),d=P(!1),f=P(null),p=P(!1);i(()=>[r.existing,r.existingKind],([e,t])=>{t===`url`&&e&&(e.startsWith(`blob:`)||e.startsWith(`data:`)||!c.value&&!d.value&&(c.value=e))},{immediate:!0});let h=I(()=>l.value&&u.value?u.value:!d.value&&r.libraryUrl?r.libraryUrl:c.value.trim()?c.value.trim():!d.value&&r.existingKind===`url`||!d.value&&r.existingKind===`file`?r.existing??``:``);i(h,()=>{p.value=!1});function g(){a(`change`,{file:l.value,url:c.value.trim(),removed:d.value})}function _(e){let t=e.target,n=t.files?.[0];if(n){if(!n.type.startsWith(`image/`)){o.error(`请选择图片文件`);return}if(n.size>s.maxAvatarMb*1024*1024){o.error(`图片不能超过 ${s.maxAvatarMb}MB`);return}l.value=n,p.value=!1,u.value&&URL.revokeObjectURL(u.value),u.value=URL.createObjectURL(n),d.value=!1,g(),t.value=``}}function v(){let e=c.value;$(()=>c.value,e=>c.value=e),(c.value!==e||c.value.trim()!==``)&&g()}function y(){p.value=!1,l.value=null,u.value&&=(URL.revokeObjectURL(u.value),``),d.value=!c.value.trim(),g()}function x(){m(y)}function S(){p.value=!1,l.value=null,u.value&&=(URL.revokeObjectURL(u.value),``),c.value=``,d.value=!0,g()}return t({clearForLibrary:()=>{l.value=null,u.value&&=(URL.revokeObjectURL(u.value),``),c.value=``,d.value=!1,p.value=!1},reset:()=>{p.value=!1,l.value=null,u.value&&=(URL.revokeObjectURL(u.value),``),c.value=``,d.value=!1}}),(e,t)=>(A(),T(`div`,be,[C(`div`,{class:`pick-area`,title:`点击选择本地图片`,onClick:t[1]||=e=>f.value?.click()},[h.value&&!p.value?(A(),T(`img`,{key:0,src:h.value,class:`pick-img`,alt:``,onError:t[0]||=e=>p.value=!0},null,40,xe)):p.value?(A(),T(`span`,Se,`图片无法加载`)):(A(),T(`span`,Ce,`点击上传`)),h.value?(A(),T(`button`,{key:3,class:`pick-x`,title:`移除图片`,onClick:L(S,[`stop`])},[O(b(G),{size:13})])):R(``,!0)]),C(`div`,we,[C(`input`,{ref_key:`logoInput`,ref:f,type:`file`,accept:`image/*`,style:{display:`none`},onChange:_},null,544),O(b(ie),{value:c.value,"onUpdate:value":t[2]||=e=>c.value=e,size:`small`,placeholder:`或粘贴在线图片地址 / 域名（自动补全 favicon 前缀）`,clearable:``,onInput:y,onClear:x,onBlur:v},null,8,[`value`]),C(`button`,{class:`pick-lib`,onClick:t[3]||=e=>a(`library`)},[O(b(_e),{size:13}),t[4]||=M(` 从文件库选择 `,-1)])])]))}}),[[`__scopeId`,`data-v-fa91d7b3`]]),Ee={class:`libpick-head`},De={key:0,class:`libpick-state`},Oe={key:1,class:`libpick-state`},ke={key:2,class:`libpick-grid`},Ae=[`title`,`onClick`],je=[`src`],Me={class:`libpick-name`},Ne=V(D({__name:`LibraryPickerModal`,props:{show:{type:Boolean}},emits:[`update:show`,`picked`],setup(e,{emit:t}){let n=e,a=t,o=P(!0),s=P([]),c=P(``),u=I(()=>{let e=c.value.trim().toLowerCase();return e?s.value.filter(t=>t.file_name.toLowerCase().includes(e)):s.value});async function f(){try{let e=await re.get(`/transfer?limit=200`);s.value=e.items.filter(e=>e.kind===`image`)}catch{s.value=[]}finally{o.value=!1}}r(f),i(()=>n.show,e=>{e&&f()});function p(e){a(`picked`,e),a(`update:show`,!1)}return(t,n)=>(A(),j(ee,{to:`body`},[e.show?(A(),T(`div`,{key:0,class:`libpick-mask`,onClick:n[3]||=e=>a(`update:show`,!1)},[C(`div`,{class:`libpick-box`,onClick:n[2]||=L(()=>{},[`stop`])},[C(`div`,Ee,[n[4]||=C(`span`,null,`从文件库选择图片`,-1),C(`button`,{onClick:n[0]||=e=>a(`update:show`,!1)},[O(b(G),{size:15})])]),d(C(`input`,{"onUpdate:modelValue":n[1]||=e=>c.value=e,class:`libpick-search`,placeholder:`搜索文件名…`},null,512),[[l,c.value]]),o.value?(A(),T(`div`,De,`加载中…`)):u.value.length?(A(),T(`div`,ke,[(A(!0),T(F,null,te(u.value,e=>(A(),T(`button`,{key:e.id,class:`libpick-cell`,title:e.file_name,onClick:t=>p(e)},[C(`img`,{src:b(w)(e.url),alt:``,loading:`lazy`},null,8,je),C(`span`,Me,E(e.file_name),1)],8,Ae))),128))])):(A(),T(`div`,Oe,`文件库中还没有图片，请先在总览快传卡上传`))])])):R(``,!0)]))}}),[[`__scopeId`,`data-v-4dfe380a`]]);export{Q as a,Z as c,$ as i,Te as n,ge as o,ye as r,ue as s,Ne as t};