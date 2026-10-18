/* Exercise the production savedata exports against a disposable Python fixture. */
#undef NDEBUG
#include "../src/runtime_savedata.c"
#include <assert.h>

static const char *fixture_root;
static char mounted_path[700];
const char *runtime_file_user_dir(void) { return fixture_root; }
int runtime_file_mount(const char *guest,const char *host) {
    assert(!strcmp(guest,"/savedata0"));
    snprintf(mounted_path,sizeof(mounted_path),"%s",host);
    return 0;
}
void runtime_file_unmount(const char *guest) { assert(!strcmp(guest,"/savedata0")); }
#ifdef _WIN32
int compat_remove_tree(const char *path) { (void)path; assert(0); return -1; }
#endif
uintptr_t runtime_lookup(const RuntimeExport *table,size_t count,const char *symbol) {
    for (size_t i=0;i<count;++i)
        if (!strcmp(table[i].name,symbol)) return (uintptr_t)table[i].function;
    return 0;
}

int main(int argc,char **argv) {
    assert(argc==4);
    fixture_root=argv[1];
    int writing=!strcmp(argv[2],"write");
    uint32_t marker=(uint32_t)strtoul(argv[3],NULL,10);
    /* CUSA00076's SFO declares INSTALL_DIR_SAVEDATA=CUSA00035. */
    runtime_savedata_configure("CUSA00035");
    typedef int32_t (ABI *InitializeFn)(const void *);
    typedef int32_t (ABI *SearchFn)(const SearchCond *,SearchResult *);
    typedef int32_t (ABI *MountFn)(const Mount2 *,MountResult *);
    typedef int32_t (ABI *UnmountFn)(const MountPoint *);
    typedef int32_t (ABI *ParamFn)(const MountPoint *,uint32_t,const void *,uint64_t);
    InitializeFn initialize=(InitializeFn)runtime_savedata_resolve("sceSaveDataInitialize");
    SearchFn search=(SearchFn)runtime_savedata_resolve("sceSaveDataDirNameSearch");
    MountFn mount_save=(MountFn)runtime_savedata_resolve("sceSaveDataMount2");
    UnmountFn unmount=(UnmountFn)runtime_savedata_resolve("sceSaveDataUmount");
    ParamFn set_param=(ParamFn)runtime_savedata_resolve("sceSaveDataSetParam");
    assert(initialize && search && mount_save && unmount && set_param);
    assert(initialize(NULL)==0);
    if (!writing) {
        DirName names[2]; Param params[2];
        SearchCond condition={.user=1};
        SearchResult found={.names=names,.names_capacity=2,.params=params};
        assert(search(&condition,&found)==0);
        assert(found.hits==2 && found.set_count==2);
        assert(!strcmp(names[0].data,"Playthrough00") && !strcmp(names[1].data,"Profile"));
        assert(params[0].user_param==marker && params[1].user_param==marker);
    }
    const char *names[]={"Playthrough00","Profile"};
    for (size_t i=0;i<2;++i) {
        DirName name={0}; snprintf(name.data,sizeof(name.data),"%s",names[i]);
        Mount2 request={.user=1,.dir=&name,.mode=writing ? MODE_CREATE2 : MODE_RDONLY};
        MountResult result;
        assert(mount_save(&request,&result)==0);
        if (!writing) assert(result.status==0);
        char path[740]; snprintf(path,sizeof(path),"%s/SYSTEM.DAT",mounted_path);
        FILE *file=fopen(path,writing ? "wb" : "rb");
        assert(file);
        uint32_t actual=0;
        if (writing) {
            assert(fwrite(&marker,sizeof(marker),1,file)==1);
            assert(set_param(&result.point,4,&marker,sizeof(marker))==0);
        } else {
            assert(fread(&actual,sizeof(actual),1,file)==1);
            assert(actual==marker);
        }
        assert(fclose(file)==0);
        assert(unmount(&result.point)==0);
    }
    puts("restored saves discovered and mounted: ok");
    return 0;
}
