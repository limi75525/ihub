import{$n as e,A as t,An as n,B as r,G as i,Ht as a,J as o,L as s,R as c,Rt as l,Ut as u,Vt as d,Wt as f,Yn as p,Z as m,at as h,cn as g,dn as _,gn as v,k as y,kn as b,ln as x,nt as S,qn as C,sn as w,w as T,z as E,zt as D}from"./vue-router-CtlYBEfb.js";import{J as O,K as k,q as A}from"./index-1sxyyN4B.js";function j(e){let{textColor2:t,primaryColorHover:n,primaryColorPressed:i,primaryColor:a,infoColor:o,successColor:s,warningColor:c,errorColor:l,baseColor:u,borderColor:d,opacityDisabled:f,tagColor:p,closeIconColor:m,closeIconColorHover:h,closeIconColorPressed:g,borderRadiusSmall:_,fontSizeMini:v,fontSizeTiny:y,fontSizeSmall:b,fontSizeMedium:x,heightMini:S,heightTiny:C,heightSmall:w,heightMedium:T,closeColorHover:E,closeColorPressed:D,buttonColor2Hover:k,buttonColor2Pressed:A,fontWeightStrong:j}=e;return{...O,closeBorderRadius:_,heightTiny:S,heightSmall:C,heightMedium:w,heightLarge:T,borderRadius:_,opacityDisabled:f,fontSizeTiny:v,fontSizeSmall:y,fontSizeMedium:b,fontSizeLarge:x,fontWeightStrong:j,textColorCheckable:t,textColorHoverCheckable:t,textColorPressedCheckable:t,textColorChecked:u,colorCheckable:`#0000`,colorHoverCheckable:k,colorPressedCheckable:A,colorChecked:a,colorCheckedHover:n,colorCheckedPressed:i,border:`1px solid ${d}`,textColor:t,color:p,colorBordered:`rgb(250, 250, 252)`,closeIconColor:m,closeIconColorHover:h,closeIconColorPressed:g,closeColorHover:E,closeColorPressed:D,borderPrimary:`1px solid ${r(a,{alpha:.3})}`,textColorPrimary:a,colorPrimary:r(a,{alpha:.12}),colorBorderedPrimary:r(a,{alpha:.1}),closeIconColorPrimary:a,closeIconColorHoverPrimary:a,closeIconColorPressedPrimary:a,closeColorHoverPrimary:r(a,{alpha:.12}),closeColorPressedPrimary:r(a,{alpha:.18}),borderInfo:`1px solid ${r(o,{alpha:.3})}`,textColorInfo:o,colorInfo:r(o,{alpha:.12}),colorBorderedInfo:r(o,{alpha:.1}),closeIconColorInfo:o,closeIconColorHoverInfo:o,closeIconColorPressedInfo:o,closeColorHoverInfo:r(o,{alpha:.12}),closeColorPressedInfo:r(o,{alpha:.18}),borderSuccess:`1px solid ${r(s,{alpha:.3})}`,textColorSuccess:s,colorSuccess:r(s,{alpha:.12}),colorBorderedSuccess:r(s,{alpha:.1}),closeIconColorSuccess:s,closeIconColorHoverSuccess:s,closeIconColorPressedSuccess:s,closeColorHoverSuccess:r(s,{alpha:.12}),closeColorPressedSuccess:r(s,{alpha:.18}),borderWarning:`1px solid ${r(c,{alpha:.35})}`,textColorWarning:c,colorWarning:r(c,{alpha:.15}),colorBorderedWarning:r(c,{alpha:.12}),closeIconColorWarning:c,closeIconColorHoverWarning:c,closeIconColorPressedWarning:c,closeColorHoverWarning:r(c,{alpha:.12}),closeColorPressedWarning:r(c,{alpha:.18}),borderError:`1px solid ${r(l,{alpha:.23})}`,textColorError:l,colorError:r(l,{alpha:.1}),colorBorderedError:r(l,{alpha:.08}),closeIconColorError:l,closeIconColorHoverError:l,closeIconColorPressedError:l,closeColorHoverError:r(l,{alpha:.12}),closeColorPressedError:r(l,{alpha:.18})}}var M={name:`Tag`,common:E,self:j},N={color:Object,type:{type:String,default:`default`},round:Boolean,size:String,closable:Boolean,disabled:{type:Boolean,default:void 0}},P=D(`tag`,`
 --n-close-margin: var(--n-close-margin-top) var(--n-close-margin-right) var(--n-close-margin-bottom) var(--n-close-margin-left);
 white-space: nowrap;
 position: relative;
 box-sizing: border-box;
 cursor: default;
 display: inline-flex;
 align-items: center;
 flex-wrap: nowrap;
 padding: var(--n-padding);
 border-radius: var(--n-border-radius);
 color: var(--n-text-color);
 background-color: var(--n-color);
 transition: 
 border-color .3s var(--n-bezier),
 background-color .3s var(--n-bezier),
 color .3s var(--n-bezier),
 box-shadow .3s var(--n-bezier),
 opacity .3s var(--n-bezier);
 line-height: 1;
 height: var(--n-height);
 font-size: var(--n-font-size);
`,[a(`strong`,`
 font-weight: var(--n-font-weight-strong);
 `),d(`border`,`
 pointer-events: none;
 position: absolute;
 left: 0;
 right: 0;
 top: 0;
 bottom: 0;
 border-radius: inherit;
 border: var(--n-border);
 transition: border-color .3s var(--n-bezier);
 `),d(`icon`,`
 display: flex;
 margin: 0 4px 0 0;
 color: var(--n-text-color);
 transition: color .3s var(--n-bezier);
 font-size: var(--n-avatar-size-override);
 `),d(`avatar`,`
 display: flex;
 margin: 0 6px 0 0;
 `),d(`close`,`
 margin: var(--n-close-margin);
 transition:
 background-color .3s var(--n-bezier),
 color .3s var(--n-bezier);
 `),a(`round`,`
 padding: 0 calc(var(--n-height) / 3);
 border-radius: calc(var(--n-height) / 2);
 `,[d(`icon`,`
 margin: 0 4px 0 calc((var(--n-height) - 8px) / -2);
 `),d(`avatar`,`
 margin: 0 6px 0 calc((var(--n-height) - 8px) / -2);
 `),a(`closable`,`
 padding: 0 calc(var(--n-height) / 4) 0 calc(var(--n-height) / 3);
 `)]),a(`icon, avatar`,[a(`round`,`
 padding: 0 calc(var(--n-height) / 3) 0 calc(var(--n-height) / 2);
 `)]),a(`disabled`,`
 cursor: not-allowed !important;
 opacity: var(--n-opacity-disabled);
 `),a(`checkable`,`
 cursor: pointer;
 box-shadow: none;
 color: var(--n-text-color-checkable);
 background-color: var(--n-color-checkable);
 `,[u(`disabled`,[l(`&:hover`,`background-color: var(--n-color-hover-checkable);`,[u(`checked`,`color: var(--n-text-color-hover-checkable);`)]),l(`&:active`,`background-color: var(--n-color-pressed-checkable);`,[u(`checked`,`color: var(--n-text-color-pressed-checkable);`)])]),a(`checked`,`
 color: var(--n-text-color-checked);
 background-color: var(--n-color-checked);
 `,[u(`disabled`,[l(`&:hover`,`background-color: var(--n-color-checked-hover);`),l(`&:active`,`background-color: var(--n-color-checked-pressed);`)])])])]),F=[`onClick`,`onMouseenter`,`onMouseleave`],I={...s.props,...N,bordered:{type:Boolean,default:void 0},checked:Boolean,checkable:Boolean,strong:Boolean,triggerClickOnClose:Boolean,onClose:[Array,Function],onMouseenter:Function,onMouseleave:Function,"onUpdate:checked":Function,onUpdateChecked:Function,internalCloseFocusable:{type:Boolean,default:!0},internalCloseIsButtonTag:{type:Boolean,default:!0},onCheckedChange:Function},L=h(`n-tag`),R=v({name:`Tag`,props:I,slots:Object,setup(e){let r=C(null),{mergedBorderedRef:a,mergedClsPrefixRef:o,inlineThemeDisabled:l,mergedRtlRef:u,mergedComponentPropsRef:d}=S(e),m=w(()=>e.size||d?.value?.Tag?.size||`medium`),h=s(`Tag`,`-tag`,P,M,e,o);n(L,{roundRef:p(e,`round`)});function g(){if(!e.disabled&&e.checkable){let{checked:t,onCheckedChange:n,onUpdateChecked:r,"onUpdate:checked":i}=e;r&&r(!t),i&&i(!t),n&&n(!t)}}function _(n){if(e.triggerClickOnClose||n.stopPropagation(),!e.disabled){let{onClose:r}=e;r&&t(r,n)}}let v={setTextContent(e){let{value:t}=r;t&&(t.textContent=e)}},y=T(`Tag`,u,o),b=w(()=>{let{type:t,color:{color:n,textColor:r}={}}=e,o=m.value,{common:{cubicBezierEaseInOut:s},self:{padding:c,closeMargin:l,borderRadius:u,opacityDisabled:d,textColorCheckable:p,textColorHoverCheckable:g,textColorPressedCheckable:_,textColorChecked:v,colorCheckable:y,colorHoverCheckable:b,colorPressedCheckable:x,colorChecked:S,colorCheckedHover:C,colorCheckedPressed:w,closeBorderRadius:T,fontWeightStrong:E,[f(`colorBordered`,t)]:D,[f(`closeSize`,o)]:O,[f(`closeIconSize`,o)]:k,[f(`fontSize`,o)]:A,[f(`height`,o)]:j,[f(`color`,t)]:M,[f(`textColor`,t)]:N,[f(`border`,t)]:P,[f(`closeIconColor`,t)]:F,[f(`closeIconColorHover`,t)]:I,[f(`closeIconColorPressed`,t)]:L,[f(`closeColorHover`,t)]:R,[f(`closeColorPressed`,t)]:z}}=h.value,B=i(l);return{"--n-font-weight-strong":E,"--n-avatar-size-override":`calc(${j} - 8px)`,"--n-bezier":s,"--n-border-radius":u,"--n-border":P,"--n-close-icon-size":k,"--n-close-color-pressed":z,"--n-close-color-hover":R,"--n-close-border-radius":T,"--n-close-icon-color":F,"--n-close-icon-color-hover":I,"--n-close-icon-color-pressed":L,"--n-close-icon-color-disabled":F,"--n-close-margin-top":B.top,"--n-close-margin-right":B.right,"--n-close-margin-bottom":B.bottom,"--n-close-margin-left":B.left,"--n-close-size":O,"--n-color":n||(a.value?D:M),"--n-color-checkable":y,"--n-color-checked":S,"--n-color-checked-hover":C,"--n-color-checked-pressed":w,"--n-color-hover-checkable":b,"--n-color-pressed-checkable":x,"--n-font-size":A,"--n-height":j,"--n-opacity-disabled":d,"--n-padding":c,"--n-text-color":r||N,"--n-text-color-checkable":p,"--n-text-color-checked":v,"--n-text-color-hover-checkable":g,"--n-text-color-pressed-checkable":_}}),x=l?c(`tag`,w(()=>{let t=``,{type:n,color:{color:r,textColor:i}={}}=e;return t+=n[0],t+=m.value[0],r&&(t+=`a${A(r)}`),i&&(t+=`b${A(i)}`),a.value&&(t+=`c`),t}),b,e):void 0;return{...v,rtlEnabled:y,mergedClsPrefix:o,contentRef:r,mergedBordered:a,handleClick:g,handleCloseClick:_,cssVars:l?void 0:b,themeClass:x?.themeClass,onRender:x?.onRender}},render(){let{mergedClsPrefix:t,rtlEnabled:n,closable:r,color:{borderColor:i}={},round:a,onRender:s,$slots:c}=this;s?.();let l=y(c.avatar,e=>e&&(b(),_(`div`,{class:o(`${t}-tag__avatar`)},[m(()=>e)],2))),u=y(c.icon,e=>e&&(b(),_(`div`,{class:o(`${t}-tag__icon`)},[m(()=>e)],2)));return b(),_(`div`,{class:o([`${t}-tag`,this.themeClass,{[`${t}-tag--rtl`]:n,[`${t}-tag--strong`]:this.strong,[`${t}-tag--disabled`]:this.disabled,[`${t}-tag--checkable`]:this.checkable,[`${t}-tag--checked`]:this.checkable&&this.checked,[`${t}-tag--round`]:a,[`${t}-tag--avatar`]:l,[`${t}-tag--icon`]:u,[`${t}-tag--closable`]:r}]),style:e(this.cssVars),onClick:this.handleClick,onMouseenter:this.onMouseenter,onMouseleave:this.onMouseleave},[m(()=>u||l),g(`span`,{class:o(`${t}-tag__content`),ref:`contentRef`},[m(()=>this.$slots.default?.())],2),!this.checkable&&r?(b(),x(k,{key:0,clsPrefix:t,class:o(`${t}-tag__close`),disabled:this.disabled,onClick:this.handleCloseClick,focusable:this.internalCloseFocusable,round:a,isButtonTag:this.internalCloseIsButtonTag,absolute:!0},null,8,[`clsPrefix`,`class`,`disabled`,`onClick`,`focusable`,`round`,`isButtonTag`])):m(()=>null),!this.checkable&&this.mergedBordered?(b(),_(`div`,{key:2,class:o(`${t}-tag__border`),style:e({borderColor:i})},null,6)):m(()=>null)],46,F)}});export{R as t};