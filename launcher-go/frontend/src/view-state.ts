export function replaceView(root:HTMLElement,markup:string){
 const previous=root.querySelector<HTMLElement>('#content');
 const scrollTop=previous?.scrollTop??0,scrollLeft=previous?.scrollLeft??0;
 const focused=root.ownerDocument.activeElement;
 const focusId=focused&&root.contains(focused)?focused.id:'';
 root.innerHTML=markup;
 const next=focusId?root.ownerDocument.getElementById(focusId):null;
 if(next&&root.contains(next)) next.focus({preventScroll:true});
 const content=root.querySelector<HTMLElement>('#content');
 if(content){content.scrollTop=scrollTop;content.scrollLeft=scrollLeft;}
}
