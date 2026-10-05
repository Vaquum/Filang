/* Independent verification-only Boolean product partition replay.
 * No Filang linkage or financial scoring. Inputs are independently checked,
 * sorted truth/validity signatures. All weighted coverage uses unsigned 128-bit.
 */
#include <stdint.h>
#include <stddef.h>
#include <stdlib.h>
#include <string.h>
#include <limits.h>
typedef unsigned __int128 U128;
typedef struct {size_t lo,hi,l,r;uint64_t weight;uint64_t *all,*any,*va,*vy;} Node;
typedef struct {Node *nodes;uint64_t *memory;size_t used,words;const uint64_t *bits,*valid,*weights;} Tree;
typedef struct {uint64_t visits,proved,leaves,words;U128 signatures,logical;} Stats;
static size_t build(Tree *t,size_t lo,size_t hi) {
    size_t left=SIZE_MAX,right=SIZE_MAX;
    if(hi-lo>1){size_t mid=lo+(hi-lo)/2;left=build(t,lo,mid);right=build(t,mid,hi);}
    size_t id=t->used++;Node *n=t->nodes+id;n->lo=lo;n->hi=hi;n->l=left;n->r=right;
    n->all=t->memory+id*t->words*4;n->any=n->all+t->words;n->va=n->any+t->words;n->vy=n->va+t->words;
    if(hi-lo==1){n->weight=t->weights[lo];for(size_t w=0;w<t->words;w++){n->all[w]=n->any[w]=t->bits[lo*t->words+w];n->va[w]=n->vy[w]=t->valid[lo*t->words+w];}}
    else {Node *a=t->nodes+left,*b=t->nodes+right;n->weight=a->weight+b->weight;for(size_t w=0;w<t->words;w++){n->all[w]=a->all[w]&b->all[w];n->any[w]=a->any[w]|b->any[w];n->va[w]=a->va[w]&b->va[w];n->vy[w]=a->vy[w]|b->vy[w];}}
    return id;
}
static int init(Tree*t,const uint64_t*b,const uint64_t*v,const uint64_t*c,size_t n,size_t w){
    if(!n||!w||n>1000000||w>100000||n>SIZE_MAX/(w*8*8))return 1;
    memset(t,0,sizeof(*t));t->words=w;t->bits=b;t->valid=v;t->weights=c;
    t->nodes=calloc(2*n,sizeof(Node));t->memory=calloc(2*n*w*4,sizeof(uint64_t));
    if(!t->nodes||!t->memory){free(t->nodes);free(t->memory);memset(t,0,sizeof(*t));return 2;}
    uint64_t sum=0;for(size_t i=0;i<n;i++){if(!c[i]||UINT64_MAX-sum<c[i]){free(t->nodes);free(t->memory);return 3;}sum+=c[i];}
    build(t,0,n);return 0;
}
static void visit(Tree*a,Tree*b,size_t ai,size_t bi,unsigned truth,int proof,Stats*s){
    Node*x=a->nodes+ai,*y=b->nodes+bi;int leaf=x->hi-x->lo==1&&y->hi-y->lo==1;
    s->visits++;int same=proof||leaf;
    if(same)for(size_t w=0;w<a->words;w++){
        uint64_t low,high;
        if(truth==8){low=x->all[w]&y->all[w];high=x->any[w]&y->any[w];}
        else if(truth==14){low=x->all[w]|y->all[w];high=x->any[w]|y->any[w];}
        else if(truth==4){low=x->all[w]&~y->any[w];high=x->any[w]&~y->all[w];}
        else {uint64_t xp[2]={~x->all[w],x->any[w]},yp[2]={~y->all[w],y->any[w]},yes=0,no=0;for(int i=0;i<2;i++)for(int j=0;j<2;j++){uint64_t z=xp[i]&yp[j];if(truth&(1u<<(i*2+j)))yes|=z;else no|=z;}low=~no;high=yes;}
        low&=x->va[w]&y->va[w];high&=x->vy[w]&y->vy[w];s->words++;
        if(low!=high){same=0;break;}
    }
    if(same){s->logical+=(U128)x->weight*y->weight;s->signatures+=(U128)(x->hi-x->lo)*(y->hi-y->lo);if(leaf)s->leaves++;else s->proved++;return;}
    if(y->hi-y->lo==1||(x->hi-x->lo>1&&x->hi-x->lo>=y->hi-y->lo)){visit(a,b,x->l,bi,truth,proof,s);visit(a,b,x->r,bi,truth,proof,s);}
    else {visit(a,b,ai,y->l,truth,proof,s);visit(a,b,ai,y->r,truth,proof,s);}
}
static int frontier(Tree*a,Tree*b,size_t id,size_t block,unsigned truth,int proof,uint64_t*out,size_t cap,size_t*used){
    Node*n=a->nodes+id;
    if(n->hi-n->lo>block){int e=frontier(a,b,n->l,block,truth,proof,out,cap,used);return e?e:frontier(a,b,n->r,block,truth,proof,out,cap,used);}
    if(*used>=cap)return 4;Stats s={0};visit(a,b,id,b->used-1,truth,proof,&s);uint64_t*z=out+(*used)++*11;
    z[0]=n->lo;z[1]=n->hi;z[2]=s.visits;z[3]=s.proved;z[4]=s.leaves;z[5]=s.words;z[6]=s.proved+s.leaves;z[7]=(uint64_t)s.signatures;z[8]=(uint64_t)(s.signatures>>64);z[9]=(uint64_t)s.logical;z[10]=(uint64_t)(s.logical>>64);return 0;
}
int dense_coverage(const uint64_t*ab,const uint64_t*av,const uint64_t*aw,size_t an,const uint64_t*bb,const uint64_t*bv,const uint64_t*bw,size_t bn,size_t words,size_t block,unsigned truth,int proof,uint64_t*out,size_t cap,size_t*used){
    if(!block||truth>15||!used||!out)return 5;Tree a,b;int e=init(&a,ab,av,aw,an,words);if(e)return e;e=init(&b,bb,bv,bw,bn,words);if(e){free(a.nodes);free(a.memory);return e;}
    *used=0;e=frontier(&a,&b,a.used-1,block,truth,proof,out,cap,used);free(a.nodes);free(a.memory);free(b.nodes);free(b.memory);return e;
}
