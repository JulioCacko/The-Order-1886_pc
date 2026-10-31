#define _GNU_SOURCE
#include <assert.h>
#include <unistd.h>
#include "../src/runtime_pad.c"
#ifdef _WIN32
#define setenv(name, value, overwrite) _putenv_s(name, value)
#endif

static int capture;
static uint8_t mouse_axes[2]={128,128};
static uint32_t mouse_buttons;
void ps4gpu_mouse_sample(uint8_t axes[2],uint32_t *buttons) {
    memcpy(axes,mouse_axes,2); *buttons=mouse_buttons;
}
static int vibration_percent=100;
static uint16_t rumble_low, rumble_high;
int ps4gpu_overlay_captures_input(void) { return capture; }
int ps4gpu_vibration_percent(void) { return vibration_percent; }

static bool SDLCALL record_rumble(void *userdata, uint16_t low, uint16_t high) {
    (void)userdata;
    rumble_low=low;
    rumble_high=high;
    return true;
}
void ps4gpu_escape_is_game_key(void) {}
int runtime_memory_is_mapped(uintptr_t address, uint64_t size) { (void)size; return address>=4096; }
uintptr_t runtime_lookup(const RuntimeExport *table, size_t count, const char *name) {
    (void)table; (void)count; (void)name;
    return 0;
}

static void inject(const char *path, const char *tokens) {
    FILE *f=fopen(path,"w");
    assert(f);
    fputs(tokens,f);
    fclose(f);
    usleep(25000);
}
static PadData read_pad(void) {
    PadData d;
    assert(pad_read_state(1,&d)==0);
    return d;
}
/* One finger in the middle of the left (480) or right (1440) half of the touchpad. */
static int touch_at(const PadData *d, int x) {
    return d->touch_count==1 && d->touches[0].x==x && d->touches[0].y==471;
}
static void pump(void) { SDL_UpdateJoysticks(); SDL_UpdateGamepads(); }

int main(void) {
#ifdef _WIN32
    /* Without a console a failed assert opens a dialog and the test run waits on it. */
    _set_error_mode(_OUT_TO_STDERR);
#endif
    /* Native Windows has no /tmp; the working directory always exists. Empty counts as unset. */
    const char *tmp=getenv("TMPDIR");
    if (!tmp || !*tmp) tmp=getenv("TEMP");
    if (!tmp || !*tmp) tmp=".";
    char path[1024];
    snprintf(path,sizeof(path),"%s/order1886-pad-test-XXXXXX",tmp);
    int fd=mkstemp(path);
    assert(fd>=0);
    close(fd);
    setenv("ORDER1886_PAD_FILE",path,1);
    setenv("SDL_VIDEODRIVER","dummy",1);
    /* Only the virtual test controller is a gamepad, whatever is plugged in. */
    SDL_SetHint(SDL_HINT_GAMECONTROLLER_IGNORE_DEVICES_EXCEPT,"0x1d50/0x6189");
    assert(SDL_Init(SDL_INIT_VIDEO|SDL_INIT_GAMEPAD));
    assert(pad_init()==0 && pad_open(1,0,0,NULL)==1);

    /* Synthetic clicks have no engine-specific delay, tail, or shoulder-button chord. */
    inject(path,"cross l3 touchpad_left");
    PadData data=read_pad();
    assert((data.buttons & (BTN_CROSS|BTN_L3|BTN_TOUCHPAD))==(BTN_CROSS|BTN_L3|BTN_TOUCHPAD));
    assert(touch_at(&data,480));
    inject(path,"");
    data=read_pad();
    assert(data.buttons==0 && data.touch_count==0);
    inject(path,"l1 touchpad_right");
    data=read_pad();
    assert((data.buttons & (BTN_L1|BTN_TOUCHPAD))==(BTN_L1|BTN_TOUCHPAD));
    assert(touch_at(&data,1440));
    capture=1;
    data=read_pad();
    assert(data.buttons==0 && data.touch_count==0);
    capture=0;
    data=read_pad();
    assert(data.buttons==0 && data.touch_count==0);
    inject(path,"");
    data=read_pad();
    inject(path,"touchpad_right");
    data=read_pad();
    assert((data.buttons & BTN_TOUCHPAD) && touch_at(&data,1440));
    inject(path,"");
    data=read_pad();
    assert(data.buttons==0 && data.touch_count==0);

    SDL_VirtualJoystickTouchpadDesc touch={.nfingers=2};
    SDL_VirtualJoystickDesc desc;
    SDL_INIT_INTERFACE(&desc);
    desc.type=SDL_JOYSTICK_TYPE_GAMEPAD;
    desc.naxes=SDL_GAMEPAD_AXIS_COUNT;
    desc.nbuttons=SDL_GAMEPAD_BUTTON_COUNT;
    desc.button_mask=(1u<<SDL_GAMEPAD_BUTTON_COUNT)-1;
    desc.axis_mask=(1u<<SDL_GAMEPAD_AXIS_COUNT)-1;
    desc.name="order1886 test controller";
    desc.vendor_id=0x1d50;
    desc.product_id=0x6189;
    desc.ntouchpads=1;
    desc.touchpads=&touch;
    desc.Rumble=record_rumble;
    SDL_JoystickID id=SDL_AttachVirtualJoystick(&desc);
    assert(id!=0);
    SDL_Joystick *joystick=SDL_OpenJoystick(id);
    assert(joystick);
    /* A real touchpad: the fingers and the click go to the game as they are. */
    assert(SDL_SetJoystickVirtualTouchpad(joystick,0,0,true,0.75f,0.5f,1.0f));
    assert(SDL_SetJoystickVirtualTouchpad(joystick,0,1,true,0.25f,1.0f,1.0f));
    assert(SDL_SetJoystickVirtualButton(joystick,SDL_GAMEPAD_BUTTON_TOUCHPAD,true));
    pump();
    data=read_pad();
    assert(gamepad && data.touch_count==2 && (data.buttons & BTN_TOUCHPAD));
    const uint8_t motors[]={255,128};
    assert(pad_vibration(1,motors)==0);
    assert(rumble_low==65535 && rumble_high==32896);
    vibration_percent=50;
    assert(pad_vibration(1,motors)==0);
    assert(rumble_low==32767 && rumble_high==16448);
    vibration_percent=0;
    assert(pad_vibration(1,motors)==0);
    assert(rumble_low==0 && rumble_high==0);
    vibration_percent=100;
    assert(data.touches[0].x==1439 && data.touches[0].y==471 && data.touches[0].id==0);
    assert(data.touches[1].x==480 && data.touches[1].y==942 && data.touches[1].id==1);
    capture=1;
    data=read_pad();
    assert(data.touch_count==0 && data.buttons==0);
    capture=0;
    /* A physical button does not invent a finger or delay release. */
    assert(SDL_SetJoystickVirtualTouchpad(joystick,0,0,false,0,0,0));
    assert(SDL_SetJoystickVirtualTouchpad(joystick,0,1,false,0,0,0));
    assert(SDL_SetJoystickVirtualButton(joystick,SDL_GAMEPAD_BUTTON_TOUCHPAD,false));
    pump();
    data=read_pad();
    assert(data.buttons==0 && data.touch_count==0);
    assert(SDL_SetJoystickVirtualButton(joystick,SDL_GAMEPAD_BUTTON_TOUCHPAD,true));
    pump();
    data=read_pad();
    assert((data.buttons & BTN_TOUCHPAD) && data.touch_count==0);
    assert(SDL_SetJoystickVirtualButton(joystick,SDL_GAMEPAD_BUTTON_TOUCHPAD,false));
    assert(SDL_SetJoystickVirtualButton(joystick,SDL_GAMEPAD_BUTTON_BACK,true));
    assert(SDL_SetJoystickVirtualButton(joystick,SDL_GAMEPAD_BUTTON_LEFT_SHOULDER,true));
    pump();
    data=read_pad();
    assert((data.buttons & (BTN_L1|BTN_TOUCHPAD))==(BTN_L1|BTN_TOUCHPAD));
    assert(touch_at(&data,1440));
    assert(SDL_SetJoystickVirtualButton(joystick,SDL_GAMEPAD_BUTTON_BACK,false));
    assert(SDL_SetJoystickVirtualButton(joystick,SDL_GAMEPAD_BUTTON_LEFT_SHOULDER,false));
    pump();
    data=read_pad();
    assert(data.buttons==0 && data.touch_count==0);
    ButtonMap original_map=pad_map;
    assert(apply_button_map(&pad_map,"cross=b,circle=none,l2=none",false)==3);
    assert(SDL_SetJoystickVirtualButton(joystick,SDL_GAMEPAD_BUTTON_EAST,true));
    pump();
    data=read_pad();
    assert((data.buttons & (BTN_CROSS|BTN_CIRCLE))==BTN_CROSS);
    assert(SDL_SetJoystickVirtualButton(joystick,SDL_GAMEPAD_BUTTON_EAST,false));
    assert(SDL_SetJoystickVirtualButton(joystick,SDL_GAMEPAD_BUTTON_SOUTH,true));
    pump();
    data=read_pad();
    assert((data.buttons & (BTN_CROSS|BTN_CIRCLE))==0);
    assert(SDL_SetJoystickVirtualButton(joystick,SDL_GAMEPAD_BUTTON_SOUTH,false));
    assert(SDL_SetJoystickVirtualAxis(joystick,SDL_GAMEPAD_AXIS_LEFT_TRIGGER,32767));
    pump();
    data=read_pad();
    assert((data.buttons & BTN_L2) && data.l2==255);
    assert(SDL_SetJoystickVirtualAxis(joystick,SDL_GAMEPAD_AXIS_LEFT_TRIGGER,0));
    pad_map=original_map;
    pump();
    mouse_axes[0]=200;
    mouse_buttons=3;
    data=read_pad();
    assert(data.right_x==200 && data.l2==255 && data.r2==255);
    assert((data.buttons & (BTN_L2|BTN_R2))==(BTN_L2|BTN_R2));
    assert(SDL_SetJoystickVirtualAxis(joystick,SDL_GAMEPAD_AXIS_RIGHTX,-32768));
    pump();
    data=read_pad();
    assert(data.right_x==0);
    capture=1;
    data=read_pad();
    assert(data.right_x==128 && data.buttons==0 && data.l2==0 && data.r2==0);
    mouse_axes[0]=128; mouse_buttons=0; capture=0;

    SDL_CloseJoystick(joystick);
    if (gamepad) SDL_CloseGamepad(gamepad);
    gamepad=NULL;
    assert(SDL_DetachVirtualJoystick(id));

    /* The Order's UI page tree: Game -> UI list -> UI -> root page -> front leaf. */
    unsigned char *image=calloc(1,ORDER_GAME+8);
    uint64_t game[0x80]={0}, list[1], ui[0x10]={0}, root[0x20]={0}, children[1], leaf[0x20]={0};
    const uint64_t player_page=ORDER_GAME_PLAYER_PAGE, game_ptr=(uintptr_t)game;
    assert(image);
    runtime_pad_attach_order(image,ORDER_GAME+8); /* another build: no menu input */
    assert(!order_image);
    memcpy(image+ORDER_PAGE_HASH,&player_page,8);
    memcpy(image+ORDER_PAGE_HASH+8,"lPrEfIxCR7GamePlayerPage",25);
    memcpy(image+ORDER_GAME,&game_ptr,8);
    game[0x348/8]=(uintptr_t)list; game[0x370/8]=1; list[0]=(uintptr_t)ui;
    ui[0]=(uintptr_t)image+ORDER_UI_VTABLE; ui[0x48/8]=(uintptr_t)root;
    root[0xa0/8]=(uintptr_t)children; root[0xc8/8]=1; children[0]=(uintptr_t)leaf;
    leaf[0x28/8]=ORDER_GAME_PLAYER_PAGE;
    runtime_pad_attach_order(image,ORDER_GAME+8);
    assert(order_image==image && !order_menu_open());
    read_pad(); /* ends the hold after the overlay capture and gamepad above */
    mouse_buttons=1|4; /* gameplay: left click fires */
    data=read_pad();
    assert((data.buttons & (BTN_R2|BTN_CROSS))==BTN_R2);
    mouse_buttons=4; /* released cursor in gameplay: nothing */
    read_pad(); mouse_buttons=0; read_pad(); mouse_buttons=4;
    data=read_pad();
    assert(!(data.buttons & (BTN_R2|BTN_CROSS)));
    mouse_buttons=0;
    leaf[0x28/8]=UINT64_C(0x6408ae4908e40599); /* PausePage */
    assert(order_menu_open());
    read_pad();
    mouse_buttons=4; /* a menu: left click selects, captured or not */
    data=read_pad();
    assert((data.buttons & (BTN_R2|BTN_CROSS))==BTN_CROSS);
    leaf[0x28/8]=ORDER_GAME_PLAYER_PAGE; /* the menu closed under a held click: still Cross */
    mouse_buttons=1|4;
    data=read_pad();
    assert((data.buttons & (BTN_R2|BTN_CROSS))==BTN_CROSS);
    mouse_buttons=0; read_pad(); mouse_buttons=1|4;
    data=read_pad();
    assert((data.buttons & (BTN_R2|BTN_CROSS))==BTN_R2);
    mouse_buttons=0; read_pad();
    root[0xc8/8]=0; /* main menu: the root's leaf is a menu page */
    leaf[0x28/8]=ORDER_GAME_PLAYER_PAGE;
    assert(order_menu_open());
    root[0xc8/8]=1; ui[0]=0; /* not the UI object: no menu */
    assert(!order_menu_open());
    bool held=false, in_menu=false; /* Esc that opened the pause menu stays Options */
    assert(!menu_route(true,&held,&in_menu,false) && !menu_route(true,&held,&in_menu,true));
    assert(!menu_route(false,&held,&in_menu,true) && menu_route(true,&held,&in_menu,true));
    order_image=NULL;
    free(image);
    SDL_Quit();
    unlink(path);
    puts("PASS: pad ABI, direct left/right clicks, unchanged shoulder input, SDL touch coordinates, overlay capture, menu clicks and Esc");
}
