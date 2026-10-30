import{B as e,Ct as t,D as n,E as r,F as i,Fn as a,Ht as o,Kt as s,M as c,St as l,T as u,U as d,Ut as f,Wt as p,Zt as m,b as h,dn as g,fn as _,jn as v,kn as y,m as b,vt as x,w as S,wt as C,xt as w,y as T,yt as E}from"./vue-router-DEBuQMrJ.js";import{g as D}from"./client-Cn9-q7d8.js";import{J as O,Y as k,q as A}from"./index-DEsgiSXB.js";function j(e){let{textColor2:t,primaryColorHover:r,primaryColorPressed:i,primaryColor:a,infoColor:o,successColor:s,warningColor:c,errorColor:l,baseColor:u,borderColor:d,opacityDisabled:f,tagColor:p,closeIconColor:m,closeIconColorHover:h,closeIconColorPressed:g,borderRadiusSmall:_,fontSizeMini:v,fontSizeTiny:y,fontSizeSmall:b,fontSizeMedium:x,heightMini:S,heightTiny:C,heightSmall:w,heightMedium:T,closeColorHover:E,closeColorPressed:D,buttonColor2Hover:O,buttonColor2Pressed:A,fontWeightStrong:j}=e;return{...k,closeBorderRadius:_,heightTiny:S,heightSmall:C,heightMedium:w,heightLarge:T,borderRadius:_,opacityDisabled:f,fontSizeTiny:v,fontSizeSmall:y,fontSizeMedium:b,fontSizeLarge:x,fontWeightStrong:j,textColorCheckable:t,textColorHoverCheckable:t,textColorPressedCheckable:t,textColorChecked:u,colorCheckable:`#0000`,colorHoverCheckable:O,colorPressedCheckable:A,colorChecked:a,colorCheckedHover:r,colorCheckedPressed:i,border:`1px solid ${d}`,textColor:t,color:p,colorBordered:`rgb(250, 250, 252)`,closeIconColor:m,closeIconColorHover:h,closeIconColorPressed:g,closeColorHover:E,closeColorPressed:D,borderPrimary:`1px solid ${n(a,{alpha:.3})}`,textColorPrimary:a,colorPrimary:n(a,{alpha:.12}),colorBorderedPrimary:n(a,{alpha:.1}),closeIconColorPrimary:a,closeIconColorHoverPrimary:a,closeIconColorPressedPrimary:a,closeColorHoverPrimary:n(a,{alpha:.12}),closeColorPressedPrimary:n(a,{alpha:.18}),borderInfo:`1px solid ${n(o,{alpha:.3})}`,textColorInfo:o,colorInfo:n(o,{alpha:.12}),colorBorderedInfo:n(o,{alpha:.1}),closeIconColorInfo:o,closeIconColorHoverInfo:o,closeIconColorPressedInfo:o,closeColorHoverInfo:n(o,{alpha:.12}),closeColorPressedInfo:n(o,{alpha:.18}),borderSuccess:`1px solid ${n(s,{alpha:.3})}`,textColorSuccess:s,colorSuccess:n(s,{alpha:.12}),colorBorderedSuccess:n(s,{alpha:.1}),closeIconColorSuccess:s,closeIconColorHoverSuccess:s,closeIconColorPressedSuccess:s,closeColorHoverSuccess:n(s,{alpha:.12}),closeColorPressedSuccess:n(s,{alpha:.18}),borderWarning:`1px solid ${n(c,{alpha:.35})}`,textColorWarning:c,colorWarning:n(c,{alpha:.15}),colorBorderedWarning:n(c,{alpha:.12}),closeIconColorWarning:c,closeIconColorHoverWarning:c,closeIconColorPressedWarning:c,closeColorHoverWarning:n(c,{alpha:.12}),closeColorPressedWarning:n(c,{alpha:.18}),borderError:`1px solid ${n(l,{alpha:.23})}`,textColorError:l,colorError:n(l,{alpha:.1}),colorBorderedError:n(l,{alpha:.08}),closeIconColorError:l,closeIconColorHoverError:l,closeIconColorPressedError:l,closeColorHoverError:n(l,{alpha:.12}),closeColorPressedError:n(l,{alpha:.18})}}var M={name:`Tag`,common:r,self:j},N={color:Object,type:{type:String,default:`default`},round:Boolean,size:String,closable:Boolean,disabled:{type:Boolean,default:void 0}},P=E(`tag`,`
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
`,[l(`strong`,`
 font-weight: var(--n-font-weight-strong);
 `),w(`border`,`
 pointer-events: none;
 position: absolute;
 left: 0;
 right: 0;
 top: 0;
 bottom: 0;
 border-radius: inherit;
 border: var(--n-border);
 transition: border-color .3s var(--n-bezier);
 `),w(`icon`,`
 display: flex;
 margin: 0 4px 0 0;
 color: var(--n-text-color);
 transition: color .3s var(--n-bezier);
 font-size: var(--n-avatar-size-override);
 `),w(`avatar`,`
 display: flex;
 margin: 0 6px 0 0;
 `),w(`close`,`
 margin: var(--n-close-margin);
 transition:
 background-color .3s var(--n-bezier),
 color .3s var(--n-bezier);
 `),l(`round`,`
 padding: 0 calc(var(--n-height) / 3);
 border-radius: calc(var(--n-height) / 2);
 `,[w(`icon`,`
 margin: 0 4px 0 calc((var(--n-height) - 8px) / -2);
 `),w(`avatar`,`
 margin: 0 6px 0 calc((var(--n-height) - 8px) / -2);
 `),l(`closable`,`
 padding: 0 calc(var(--n-height) / 4) 0 calc(var(--n-height) / 3);
 `)]),l(`icon, avatar`,[l(`round`,`
 padding: 0 calc(var(--n-height) / 3) 0 calc(var(--n-height) / 2);
 `)]),l(`disabled`,`
 cursor: not-allowed !important;
 opacity: var(--n-opacity-disabled);
 `),l(`checkable`,`
 cursor: pointer;
 box-shadow: none;
 color: var(--n-text-color-checkable);
 background-color: var(--n-color-checkable);
 `,[t(`disabled`,[x(`&:hover`,`background-color: var(--n-color-hover-checkable);`,[t(`checked`,`color: var(--n-text-color-hover-checkable);`)]),x(`&:active`,`background-color: var(--n-color-pressed-checkable);`,[t(`checked`,`color: var(--n-text-color-pressed-checkable);`)])]),l(`checked`,`
 color: var(--n-text-color-checked);
 background-color: var(--n-color-checked);
 `,[t(`disabled`,[x(`&:hover`,`background-color: var(--n-color-checked-hover);`),x(`&:active`,`background-color: var(--n-color-checked-pressed);`)])])])]),F=[`onClick`,`onMouseenter`,`onMouseleave`],I={...S.props,...N,bordered:{type:Boolean,default:void 0},checked:Boolean,checkable:Boolean,strong:Boolean,triggerClickOnClose:Boolean,onClose:[Array,Function],onMouseenter:Function,onMouseleave:Function,"onUpdate:checked":Function,onUpdateChecked:Function,internalCloseFocusable:{type:Boolean,default:!0},internalCloseIsButtonTag:{type:Boolean,default:!0},onCheckedChange:Function},L=d(`n-tag`),R=m({name:`Tag`,props:I,slots:Object,setup(t){let n=y(null),{mergedBorderedRef:r,mergedClsPrefixRef:i,inlineThemeDisabled:a,mergedRtlRef:s,mergedComponentPropsRef:c}=e(t),l=o(()=>t.size||c?.value?.Tag?.size||`medium`),d=S(`Tag`,`-tag`,P,M,t,i);_(L,{roundRef:v(t,`round`)});function f(){if(!t.disabled&&t.checkable){let{checked:e,onCheckedChange:n,onUpdateChecked:r,"onUpdate:checked":i}=t;r&&r(!e),i&&i(!e),n&&n(!e)}}function p(e){if(t.triggerClickOnClose||e.stopPropagation(),!t.disabled){let{onClose:n}=t;n&&h(n,e)}}let m={setTextContent(e){let{value:t}=n;t&&(t.textContent=e)}},g=b(`Tag`,s,i),x=o(()=>{let{type:e,color:{color:n,textColor:i}={}}=t,a=l.value,{common:{cubicBezierEaseInOut:o},self:{padding:s,closeMargin:c,borderRadius:u,opacityDisabled:f,textColorCheckable:p,textColorHoverCheckable:m,textColorPressedCheckable:h,textColorChecked:g,colorCheckable:_,colorHoverCheckable:v,colorPressedCheckable:y,colorChecked:b,colorCheckedHover:x,colorCheckedPressed:S,closeBorderRadius:w,fontWeightStrong:T,[C(`colorBordered`,e)]:E,[C(`closeSize`,a)]:O,[C(`closeIconSize`,a)]:k,[C(`fontSize`,a)]:A,[C(`height`,a)]:j,[C(`color`,e)]:M,[C(`textColor`,e)]:N,[C(`border`,e)]:P,[C(`closeIconColor`,e)]:F,[C(`closeIconColorHover`,e)]:I,[C(`closeIconColorPressed`,e)]:L,[C(`closeColorHover`,e)]:R,[C(`closeColorPressed`,e)]:z}}=d.value,B=D(c);return{"--n-font-weight-strong":T,"--n-avatar-size-override":`calc(${j} - 8px)`,"--n-bezier":o,"--n-border-radius":u,"--n-border":P,"--n-close-icon-size":k,"--n-close-color-pressed":z,"--n-close-color-hover":R,"--n-close-border-radius":w,"--n-close-icon-color":F,"--n-close-icon-color-hover":I,"--n-close-icon-color-pressed":L,"--n-close-icon-color-disabled":F,"--n-close-margin-top":B.top,"--n-close-margin-right":B.right,"--n-close-margin-bottom":B.bottom,"--n-close-margin-left":B.left,"--n-close-size":O,"--n-color":n||(r.value?E:M),"--n-color-checkable":_,"--n-color-checked":b,"--n-color-checked-hover":x,"--n-color-checked-pressed":S,"--n-color-hover-checkable":v,"--n-color-pressed-checkable":y,"--n-font-size":A,"--n-height":j,"--n-opacity-disabled":f,"--n-padding":s,"--n-text-color":i||N,"--n-text-color-checkable":p,"--n-text-color-checked":g,"--n-text-color-hover-checkable":m,"--n-text-color-pressed-checkable":h}}),w=a?u(`tag`,o(()=>{let e=``,{type:n,color:{color:i,textColor:a}={}}=t;return e+=n[0],e+=l.value[0],i&&(e+=`a${O(i)}`),a&&(e+=`b${O(a)}`),r.value&&(e+=`c`),e}),x,t):void 0;return{...m,rtlEnabled:g,mergedClsPrefix:i,contentRef:n,mergedBordered:r,handleClick:f,handleCloseClick:p,cssVars:a?void 0:x,themeClass:w?.themeClass,onRender:w?.onRender}},render(){let{mergedClsPrefix:e,rtlEnabled:t,closable:n,color:{borderColor:r}={},round:o,onRender:l,$slots:u}=this;l?.();let d=T(u.avatar,t=>t&&(g(),s(`div`,{class:c(`${e}-tag__avatar`)},[i(()=>t)],2))),m=T(u.icon,t=>t&&(g(),s(`div`,{class:c(`${e}-tag__icon`)},[i(()=>t)],2)));return g(),s(`div`,{class:c([`${e}-tag`,this.themeClass,{[`${e}-tag--rtl`]:t,[`${e}-tag--strong`]:this.strong,[`${e}-tag--disabled`]:this.disabled,[`${e}-tag--checkable`]:this.checkable,[`${e}-tag--checked`]:this.checkable&&this.checked,[`${e}-tag--round`]:o,[`${e}-tag--avatar`]:d,[`${e}-tag--icon`]:m,[`${e}-tag--closable`]:n}]),style:a(this.cssVars),onClick:this.handleClick,onMouseenter:this.onMouseenter,onMouseleave:this.onMouseleave},[i(()=>m||d),f(`span`,{class:c(`${e}-tag__content`),ref:`contentRef`},[i(()=>this.$slots.default?.())],2),!this.checkable&&n?(g(),p(A,{key:0,clsPrefix:e,class:c(`${e}-tag__close`),disabled:this.disabled,onClick:this.handleCloseClick,focusable:this.internalCloseFocusable,round:o,isButtonTag:this.internalCloseIsButtonTag,absolute:!0},null,8,[`clsPrefix`,`class`,`disabled`,`onClick`,`focusable`,`round`,`isButtonTag`])):i(()=>null),!this.checkable&&this.mergedBordered?(g(),s(`div`,{key:2,class:c(`${e}-tag__border`),style:a({borderColor:r})},null,6)):i(()=>null)],46,F)}});export{R as t};