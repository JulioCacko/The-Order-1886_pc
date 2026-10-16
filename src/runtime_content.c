/* Offline AppContent metadata from the application's param.sfo.
 * No package/DLC mounting, downloads, entitlement or license emulation. */
#include "runtime.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define INVALID_ID ((int32_t)0x805a1000)
#define NOT_LOADED ((int32_t)0x805a1001)
#define PARAMETER ((int32_t)0x80d90002)
#define BUSY ((int32_t)0x80d90003)
#define NOT_FOUND ((int32_t)0x80d90005)
#define NO_ENTITLEMENT ((int32_t)0x80d90007)
static unsigned refs, initialized, configured;
static uint32_t parameters[5];
static unsigned queries, lists;
static void stop(const char *message,int status) {
    fputs(message,stderr); fflush(NULL); _Exit(status);
}
/* PSF tables and strings are bounded before any offset or typed value is read. */
int runtime_sfo_value(const char *path,const char *key,char *text,size_t text_size,uint32_t *number) {
    if (!path || !key) return 0;
    FILE *file=fopen(path,"rb");
    if (!file) return 0;
    unsigned char data[65536];
    size_t size=fread(data,1,sizeof(data),file);
    int extra=fgetc(file), failed=ferror(file);
    fclose(file);
    if (failed || extra!=EOF || size<20 || memcmp(data,"\0PSF",4)) return 0;
    uint32_t version,keys,values,count;
    memcpy(&version,data+4,4); memcpy(&keys,data+8,4); memcpy(&values,data+12,4); memcpy(&count,data+16,4);
    if (version!=0x101 || count>(size-20)/16 || keys<20+(size_t)count*16 || keys>values || values>size) return 0;
    const unsigned char *selected=NULL;
    uint16_t selected_format=0; uint32_t selected_length=0;
    for (uint32_t i=0;i<count;++i) {
        const unsigned char *entry=data+20+(size_t)i*16;
        uint16_t key_offset,format; uint32_t length,maximum,offset;
        memcpy(&key_offset,entry,2); memcpy(&format,entry+2,2); memcpy(&length,entry+4,4);
        memcpy(&maximum,entry+8,4); memcpy(&offset,entry+12,4);
        if (key_offset>=values-keys || !memchr(data+keys+key_offset,0,values-keys-key_offset) ||
            offset>size-values || length>maximum || maximum>size-values-offset) return 0;
        if (strcmp((const char *)data+keys+key_offset,key)) continue;
        if (selected) return 0;
        selected=data+values+offset; selected_format=format; selected_length=length;
    }
    if (!selected) return 0;
    if (selected_format==0x0404 && number && selected_length==4) { memcpy(number,selected,4); return 1; }
    if (selected_format==0x0204 && text && text_size && selected_length && memchr(selected,0,selected_length)) {
        size_t copy=strlen((const char *)selected);
        if (copy>=text_size) copy=text_size-1;
        memcpy(text,selected,copy); text[copy]=0; return 1;
    }
    return 0;
}
void runtime_content_configure(const uint32_t values[5]) {
    if (!values || refs || initialized || (values[0]!=1 && values[0]!=3))
        stop("ERROR: invalid or late AppContent metadata\n",1);
    memcpy(parameters,values,sizeof(parameters)); configured=1;
}
int runtime_content_configure_sfo(const char *path) {
    char title[16];
    if (!runtime_sfo_value(path,"TITLE_ID",title,sizeof(title),NULL) || !title[0]) return 0;
    /* The supplied shadPS4 AppContent implementation returns FULL=3 for SKU;
     * this compatibility value is not a license or entitlement determination. */
    uint32_t values[5]={3,0,0,0,0};
    for (unsigned i=1;i<5;++i) {
        char key[32]; snprintf(key,sizeof(key),"USER_DEFINED_PARAM_%u",i);
        runtime_sfo_value(path,key,NULL,0,&values[i]);
    }
    runtime_content_configure(values);
    printf("Runtime: AppContent SFO %s: SKU=3 (reference compatibility value), user parameters=%u,%u,%u,%u; no add-ons configured\n",
           title,values[1],values[2],values[3],values[4]);
    return 1;
}
/* System modules: every library this eboot imports is provided by the host
 * runtime, so loading one only tracks a reference count. */
static unsigned module_refs[0x10000];
static ABI int32_t module_load(uint16_t id) {
    if (!id) return INVALID_ID;
    if (module_refs[id]==UINT32_MAX) stop("STOP: module reference overflow\n",21);
    ++module_refs[id];
    if (id==0xb4) { refs=module_refs[id]; printf("Runtime: AppContent host provider loaded; references=%u\n",refs); }
    else printf("Runtime: system module 0x%x loaded (host implementation)\n",id);
    return 0;
}
static ABI int32_t module_loaded(uint16_t id) {
    if (!id) return INVALID_ID;
    return module_refs[id] ? 0 : NOT_LOADED;
}
static ABI int32_t module_unload(uint16_t id) {
    int32_t result=module_loaded(id);
    if (result) return result;
    --module_refs[id];
    if (id==0xb4) { refs=module_refs[id]; if (!refs) initialized=0; }
    return 0;
}
static ABI int32_t content_init(const unsigned char *init,unsigned char *boot) {
    if (!configured || !init || !boot) return PARAMETER;
    if (initialized) return BUSY;
    /* The public init structure contains only reserved bytes. */
    for (unsigned i=0;i<32;++i) if (init[i]) return PARAMETER;
    memset(boot,0,40); initialized=1;
    puts("Runtime: AppContent initialized from application metadata; no mounted add-ons");
    return 0;
}
static ABI int32_t param_int(uint32_t id,int32_t *out) {
    if (!configured || id>4 || !out) return PARAMETER;
    memcpy(out,&parameters[id],4); ++queries;
    printf("Runtime: AppContent parameter %u = %d\n",id,*out);
    return 0;
}
static ABI int32_t addon_list(uint32_t service,void *list,uint32_t capacity,uint32_t *hits) {
    (void)service;
    if (!configured) return PARAMETER;
    if ((!capacity || !list) && !hits) return PARAMETER;
    /* No add-ons are mounted by this provider. Never touch unused list slots. */
    if (hits) *hits=0;
    ++lists; return 0;
}
static ABI int32_t addon_mount(uint32_t service,const void *label,void *mount_point) {
    (void)service;
    if (!configured || !label || !mount_point) return PARAMETER;
    return NOT_FOUND;
}
static ABI int32_t entitlement_key(uint32_t service,const void *label,void *key) {
    (void)service;
    if (!configured || !label || !key) return PARAMETER;
    return NO_ENTITLEMENT;
}
uintptr_t runtime_content_resolve(const char *name) {
    if (!strcmp(name,"g8cM39EUZ6o#libSceSysmodule")) return (uintptr_t)module_load;
    if (!strcmp(name,"fMP5NHUOaMk#libSceSysmodule")) return (uintptr_t)module_loaded;
    if (!strcmp(name,"eR2bZFAAU0Q#libSceSysmodule")) return (uintptr_t)module_unload;
    if (!strcmp(name,"R9lA82OraNs#libSceAppContent")) return (uintptr_t)content_init;
    if (!strcmp(name,"99b82IKXpH4#libSceAppContent")) return (uintptr_t)param_int;
    if (!strcmp(name,"xnd8BJzAxmk#libSceAppContent")) return (uintptr_t)addon_list;
    if (!strcmp(name,"VANhIWcqYak#libSceAppContent")) return (uintptr_t)addon_mount;
    if (!strcmp(name,"XTWR0UXvcgs#libSceAppContent")) return (uintptr_t)entitlement_key;
    return 0;
}
void runtime_content_report(void) {
    printf("Runtime: AppContent references=%u, initialized=%u, parameter queries=%u, list queries=%u\n",refs,initialized,queries,lists);
}
