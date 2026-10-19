import test from 'node:test';
import assert from 'node:assert/strict';
import {replaceView} from '../.test-build/view-state.js';

test('polling keeps a scrolled achievement list and keyboard focus after replacing nodes',()=>{
 const oldContent={scrollTop:760,scrollLeft:12};
 const newContent={scrollTop:0,scrollLeft:0};
 let currentContent=oldContent;
 let focusOptions;
 const oldFocus={id:'launch'};
 const newFocus={focus(options){focusOptions=options;newContent.scrollTop=0;}};
 const root={ownerDocument:{activeElement:oldFocus,getElementById:()=>newFocus},
  contains:()=>true,querySelector:()=>currentContent,
  set innerHTML(value){assert.equal(value,'new markup');currentContent=newContent;}};
 replaceView(root,'new markup');
 assert.equal(currentContent,newContent);
 assert.equal(newContent.scrollTop,760);
 assert.equal(newContent.scrollLeft,12);
 assert.deepEqual(focusOptions,{preventScroll:true});
});
