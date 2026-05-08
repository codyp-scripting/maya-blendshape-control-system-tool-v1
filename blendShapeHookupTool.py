###################################################
# Automated BlendShape Control Connection Tool v1 #
###################################################

# Author: Cody P
# Version: 1.0

#Procedural node creation, range remapping, non-destructive rigging, data-driven, naming convention automation

#Script order: query scene info, create utility functions, build node networks, handle special cases,
#              disconnect systems, handle ui callbacks, build ui

import maya.cmds as cmds

WINDOW_NAME  = "blendShapeHookupTool"
WINDOW_TITLE = "BlendShape Hookup Tool"



# SCENE QUERIES  

#Scans scene and returns all blendshape nodes
def get_blendshape_nodes():
    return cmds.ls(type="blendShape") or [] #Find all nodes of type blendShape / populate dropdown


#Get target names from blendshape node
def get_blendshape_targets(bs):
    if not bs or not cmds.objExists(bs):
        return []
    #Extract usable target names from blendshape node
    aliases = cmds.aliasAttr(bs, q=True) or []
    return [aliases[i] for i in range(0, len(aliases), 2)
            if not aliases[i].startswith("weight")]


#Check target for incoming connections (bs targets only allow one incoming connection)
def get_connection_status(ctrl, bs, target):
    if not all([ctrl, bs, target]):
        return ""
    plug = f"{bs}.{target}"
    if not cmds.objExists(plug):
        return ""
    #What node is currently driving this target?
    sources = cmds.listConnections(plug, source=True, destination=False, plugs=True) or []
    #If something exists:
    return f"Connected  <-  {sources[0]}" if sources else "Not connected"



# UTILITY FUNCTIONS


#Reusable helper functions

#If a node with this name already exists, add a numeric suffix
#Prevent node naming conflicts / avoid overwriting existing nodes
def unique_name(base, suffix):
    name = f"{base}_{suffix}"
    if not cmds.objExists(name):
        return name
    i = 1
    while cmds.objExists(f"{name}_{i:03d}"):
        i += 1
    return f"{name}_{i:03d}"


#Add animator-friendly-facing attribute to control
def add_float_attr(ctrl, long_name, nice_name, default, min_val=None):
    #Create numeric float channel and visible in channel box
    if not cmds.attributeQuery(long_name, node=ctrl, exists=True):
        kwargs = dict(longName=long_name, niceName=nice_name,
                      attributeType="float", defaultValue=default, keyable=True)
        if min_val is not None:
            kwargs["minValue"] = min_val
        cmds.addAttr(ctrl, **kwargs)
    return f"{ctrl}.{long_name}"




# SYSTEM/CONNECTION BUILDER


#Decide nodes to build, direction to map, whether to use unified mode, if inversion is needed
#Routing logic
def build_connections(ctrl, bs, target, axes, bs_range):
    
    #loop through enabled axes
    #Each axes stores settings in a dictionary
   
    for a in axes:
        axis   = a["axis"]
        do_pos = a["positive"]
        do_neg = a["negative"]
        invert = a["invert"]
        travel = a["travel"]
        #Create driver plug
        #example: mouth_CTRL.translateX
        src    = f"{ctrl}.translate{axis}"

        if not do_pos and not do_neg:
            cmds.warning(f"Axis {axis}: neither Positive nor Negative — skipped.")
            continue

        #Add travel limit attribute to the control (remap distance live in channel box)
        travel_attr = add_float_attr(
            ctrl,
            long_name=f"bs_{target}_{axis}_Travel",
            nice_name=f"{target} {axis} Travel",
            default=travel,
            min_val=0.001
        )
        cmds.setAttr(travel_attr, travel)

        #Both directions on a -1 to 1 target share same plug
        #So build one unified chain instead of two conflicting ones
        if do_pos and do_neg and bs_range == "-1_to_1":
            wire_unified(src, travel_attr, bs, target, invert, axis)
            continue

        #Single direction wiring 
        #Invert swaps which side gets which sign
        pos_sign = -1.0 if invert else  1.0
        neg_sign =  1.0 if invert else -1.0

        if do_pos:
            wire_one_direction(src, travel_attr, bs, target, bs_range, axis, "POS", pos_sign)

        if do_neg:
            #Check if there is an obvious opposite target to drive (example: brow_Up -> brow_Dn)
            opposite = find_opposite_target(bs, target) if do_pos else None
            neg_target = opposite if opposite else target
            wire_one_direction(src, travel_attr, bs, neg_target, bs_range, axis, "NEG", neg_sign)



# UNIFIED CHAIN  (both directions, -1 to 1)


#Used when positive + negative AND blendshape range -1 to 1
#Instead of building two conflicting networks(one for positive, one for negative)
#Creates one continuous mapping


def wire_unified(src, travel_attr, bs, target, invert, axis):

    #MultiplyDivide node: travel * -1 (oldMin = -travel; oldMax = +travel)
    #Editing travel range attribute updates both ends of the remap
    neg_node = cmds.createNode("multiplyDivide", name=unique_name(f"{target}_{axis}_UNIFIED", "NEG"))
    cmds.setAttr(f"{neg_node}.operation", 1)
    cmds.connectAttr(travel_attr, f"{neg_node}.input1X", force=True)
    cmds.setAttr(f"{neg_node}.input2X", -1.0)

    #setRange maps one numerical range into another
    #Input range -> Output range
    #Example: -3 to 3 -> -1 to 1
    sr = cmds.createNode("setRange", name=unique_name(f"{target}_{axis}_UNIFIED", "SR"))
    cmds.connectAttr(src, f"{sr}.valueX",  force=True)
    cmds.connectAttr(f"{neg_node}.outputX", f"{sr}.oldMinX", force=True)
    cmds.connectAttr(travel_attr, f"{sr}.oldMaxX", force=True)

    if invert:
        cmds.setAttr(f"{sr}.minX",  1.0)
        cmds.setAttr(f"{sr}.maxX", -1.0)
    else:
        cmds.setAttr(f"{sr}.minX", -1.0)
        cmds.setAttr(f"{sr}.maxX",  1.0)

    #Clamp to -1 -> 1 as a safety net against overshoots
    #Limit output
    clamp = cmds.createNode("clamp", name=unique_name(f"{target}_{axis}_UNIFIED", "CLAMP"))
    cmds.connectAttr(f"{sr}.outValueX",    f"{clamp}.inputR", force=True)
    cmds.setAttr(f"{clamp}.minR", -1.0)
    cmds.setAttr(f"{clamp}.maxR",  1.0)

    cmds.connectAttr(f"{clamp}.outputR", f"{bs}.{target}", force=True)



# SINGLE DIRECTION CHAIN


#Handle simpler setups (only positive; only negative)

#Builds node chain for one translate direction
#Sign = +1; output goes 0 to 1
#Sign = -1: output goes 0 to -1 (second setRange at end)
#Translate value always made positive before entering setRange
#Negative direction - multiply by -1 first
#Positive direction - already positive

def wire_one_direction(src, travel_attr, bs, target, bs_range, axis, tag, sign):

    #Negative direction produces negative translate values, flip to positive
    #setRange always receives a 0 to +travel input

    if tag == "NEG":
        flip = cmds.createNode("multiplyDivide", name=unique_name(f"{target}_{axis}_{tag}", "FLIP"))
        cmds.setAttr(f"{flip}.operation", 1)
        cmds.connectAttr(src, f"{flip}.input1X", force=True)
        cmds.setAttr(f"{flip}.input2X", -1.0)
        remap_input = f"{flip}.outputX"
    else:
        remap_input = src

    #Remap 0; travel 0 to 1
    #Travel staying live via attribute connection
    sr = cmds.createNode("setRange", name=unique_name(f"{target}_{axis}_{tag}", "SR"))
    cmds.connectAttr(remap_input,  f"{sr}.valueX",  force=True)
    cmds.setAttr(f"{sr}.oldMinX",  0.0)
    cmds.connectAttr(travel_attr,  f"{sr}.oldMaxX", force=True)
    cmds.setAttr(f"{sr}.minX",     0.0)
    cmds.setAttr(f"{sr}.maxX",     1.0)

    #Clamp 0 to 1 as a safety net
    clamp = cmds.createNode("clamp", name=unique_name(f"{target}_{axis}_{tag}", "CLAMP"))
    cmds.connectAttr(f"{sr}.outValueX", f"{clamp}.inputR", force=True)
    cmds.setAttr(f"{clamp}.minR", 0.0)
    cmds.setAttr(f"{clamp}.maxR", 1.0)

    # Negative sign: need to remap 0 to 1 -> -1 to 0 so blendshape receives proper negative weight
    #Only exists when output needs to become negative again

    #Convert back into negative output range
    #Negative translate -> flipped positive -> remapped 0 to 1 -> remapped again -1 to 0

    if bs_range == "-1_to_1" and sign < 0:
        sr2 = cmds.createNode("setRange", name=unique_name(f"{target}_{axis}_{tag}", "SR2"))
        cmds.setAttr(f"{sr2}.oldMinX",  0.0)
        cmds.setAttr(f"{sr2}.oldMaxX",  1.0)
        cmds.setAttr(f"{sr2}.minX",    -1.0)
        cmds.setAttr(f"{sr2}.maxX",     0.0)
        cmds.connectAttr(f"{clamp}.outputR", f"{sr2}.valueX",    force=True)
        cmds.connectAttr(f"{sr2}.outValueX", f"{bs}.{target}",   force=True)
    else:
        cmds.connectAttr(f"{clamp}.outputR", f"{bs}.{target}", force=True)



# OPPOSITE TARGET LOOKUP


#Naming convention helper
#Use naming conventions to infer relationships

#Find paired target on the other side of a movement
#Example: brow_Up -> brow_Dn,  mouth_L -> mouth_R

def find_opposite_target(bs, target):
    all_targets = get_blendshape_targets(bs)
    pairs = [("_L",    "_R"),     ("_R",    "_L"),
             ("_Up",   "_Dn"),    ("_Dn",   "_Up"),
             ("_Open", "_Close"), ("_Close","_Open"),
             ("_Pos",  "_Neg"),   ("_Neg",  "_Pos"),
             ("_pos",  "_neg"),   ("_neg",  "_pos")]
    for a, b in pairs:
        if target.endswith(a):
            candidate = target[:-len(a)] + b
            if candidate in all_targets:
                return candidate
    return None



# DISCONNECT


#Cut all incoming connections to a blendshape target
#Automated node editor -> break connection

def disconnect_target(bs, target):
    plug = f"{bs}.{target}"
    sources = cmds.listConnections(plug, source=True, destination=False, plugs=True) or []
    if not sources:
        cmds.warning(f"'{target}' has no incoming connections.")
        return
    for src in sources:
        cmds.disconnectAttr(src, plug)
    cmds.inViewMessage(amg=f'<hl>{target}</hl> disconnected.', pos='topCenter', fade=True)



# UI CALLBACKS

#Read UI values
#Update menus
#Call builder functions

def _load_selected_control(*args):
    sel = cmds.ls(selection=True)
    #Error handling: select a control
    if not sel:
        cmds.warning("Select a control first.")
        return
    cmds.textFieldButtonGrp("controlField", e=True, text=sel[0])
    _refresh_status()


def _populate_targets(*args):
    items = cmds.optionMenu("targetMenu", q=True, itemListLong=True) or []
    for item in items:
        cmds.deleteUI(item)
    bs = cmds.optionMenu("blendshapeMenu", q=True, value=True)
    for t in get_blendshape_targets(bs):
        cmds.menuItem(label=t, parent="targetMenu")
    _refresh_status()


def _refresh_status(*args):
    ctrl   = cmds.textFieldButtonGrp("controlField",  q=True, text=True)
    bs     = cmds.optionMenu("blendshapeMenu", q=True, value=True)
    target = cmds.optionMenu("targetMenu",     q=True, value=True)
    status = get_connection_status(ctrl, bs, target)
    cmds.text("statusText", e=True, label=f"Status:  {status}" if status else "Status:  —")


#Gather user settings and send to build_connections( )
def _on_connect(*args):
    ctrl   = cmds.textFieldButtonGrp("controlField",  q=True, text=True)
    bs     = cmds.optionMenu("blendshapeMenu", q=True, value=True)
    target = cmds.optionMenu("targetMenu",     q=True, value=True)
    bs_range = "0_to_1" if cmds.radioButtonGrp("bsRangeGrp", q=True, select=True) == 1 else "-1_to_1"

    if not ctrl:
        cmds.warning("No control loaded."); return
    if not cmds.objExists(ctrl):
        cmds.warning(f"Control '{ctrl}' not found in scene."); return
    if not bs or not cmds.objExists(bs):
        cmds.warning("BlendShape node not found."); return
    if not target:
        cmds.warning("No target selected."); return

    axes = []
    for axis in ("X", "Y", "Z"):
        if not cmds.checkBox(f"axisCheck{axis}", q=True, value=True):
            continue
        axes.append({
            "axis"    : axis,
            "positive": cmds.checkBox(f"posCheck{axis}",        q=True, value=True),
            "negative": cmds.checkBox(f"negCheck{axis}",        q=True, value=True),
            "invert"  : cmds.checkBox(f"invertCheck{axis}",     q=True, value=True),
            "travel"  : cmds.floatSliderGrp(f"travelSlider{axis}", q=True, value=True),
        })

    if not axes:
        cmds.warning("Enable at least one axis (X / Y / Z)."); return

    build_connections(ctrl, bs, target, axes, bs_range)

    label_list = ", ".join(a["axis"] for a in axes)
    cmds.inViewMessage(
        amg=f'<hl>{target}</hl> connected on {label_list} ({bs_range.replace("_", " ")})',
        pos='topCenter', fade=True)
    _refresh_status()


def _on_disconnect(*args):
    bs     = cmds.optionMenu("blendshapeMenu", q=True, value=True)
    target = cmds.optionMenu("targetMenu",     q=True, value=True)
    if not bs or not target:
        cmds.warning("Select a blendshape node and target first."); return
    disconnect_target(bs, target)
    _refresh_status()


def _toggle_axis_row(axis, *args):
    enabled = cmds.checkBox(f"axisCheck{axis}", q=True, value=True)
    cmds.checkBox(f"posCheck{axis}",           e=True, enable=enabled)
    cmds.checkBox(f"negCheck{axis}",           e=True, enable=enabled)
    cmds.checkBox(f"invertCheck{axis}",        e=True, enable=enabled)
    cmds.floatSliderGrp(f"travelSlider{axis}", e=True, enable=enabled)



# BUILD UI

def create_ui():
    if cmds.window(WINDOW_NAME, exists=True):
        cmds.deleteUI(WINDOW_NAME)

    win = cmds.window(WINDOW_NAME, title=WINDOW_TITLE, sizeable=True, width=480)

    cmds.columnLayout(adjustableColumn=True, rowSpacing=6, columnAlign="center")
    cmds.separator(height=8, style="none")
    cmds.text(label="BlendShape Hookup Tool", height=28, font="boldLabelFont")
    cmds.separator(height=8, style="in")

    cmds.frameLayout(label="Control", collapsable=False, marginHeight=6, marginWidth=6)
    cmds.textFieldButtonGrp("controlField", label="Control  ",
                            buttonLabel="Load Selected",
                            buttonCommand=_load_selected_control,
                            columnWidth3=[80, 240, 110])
    cmds.setParent("..")
    cmds.separator(height=4, style="none")

    cmds.frameLayout(label="BlendShape", collapsable=False, marginHeight=6, marginWidth=6)
    cmds.columnLayout(adjustableColumn=True, rowSpacing=4)

    cmds.optionMenu("blendshapeMenu", label="Node           ", changeCommand=_populate_targets)
    bs_nodes = get_blendshape_nodes()
    if bs_nodes:
        for n in bs_nodes:
            cmds.menuItem(label=n)
    else:
        cmds.menuItem(label="(none found)")

    cmds.optionMenu("targetMenu", label="Target          ", changeCommand=_refresh_status)
    if bs_nodes:
        for t in get_blendshape_targets(bs_nodes[0]):
            cmds.menuItem(label=t, parent="targetMenu")

    cmds.separator(height=4, style="none")
    cmds.radioButtonGrp("bsRangeGrp", label="BS Range      ",
                        labelArray2=["0  to  1", "-1  to  1"],
                        numberOfRadioButtons=2, select=1,
                        columnWidth3=[100, 100, 100])
    cmds.setParent("..")
    cmds.setParent("..")
    cmds.separator(height=4, style="none")

    cmds.frameLayout(label="Axis  /  Direction  /  Travel Limit",
                     collapsable=False, marginHeight=6, marginWidth=6)
    cmds.columnLayout(adjustableColumn=True, rowSpacing=2)

    COL_W = [38, 90, 45, 45, 50, 160]
    cmds.rowLayout(numberOfColumns=6, columnWidth6=COL_W, columnAlign6=["center"]*6)
    cmds.text(label="On")
    cmds.text(label="Axis")
    cmds.text(label="Pos")
    cmds.text(label="Neg")
    cmds.text(label="Invert")
    cmds.text(label="Travel Limit (units)")
    cmds.setParent("..")
    cmds.separator(height=4, style="in")

    for axis in ("X", "Y", "Z"):
        is_x = (axis == "X")
        cmds.rowLayout(numberOfColumns=6, columnWidth6=COL_W,
                       columnAlign6=["center"]*6,
                       columnAttach6=["both"]*6,
                       columnOffset6=[2]*6)
        cmds.checkBox(f"axisCheck{axis}", label="", value=is_x,
                      changeCommand=lambda v, a=axis: _toggle_axis_row(a))
        cmds.text(label=f"Translate {axis}", align="center")
        cmds.checkBox(f"posCheck{axis}",    label="", value=True,  enable=is_x)
        cmds.checkBox(f"negCheck{axis}",    label="", value=False, enable=is_x)
        cmds.checkBox(f"invertCheck{axis}", label="", value=False, enable=is_x)
        cmds.floatSliderGrp(f"travelSlider{axis}", value=1.0,
                            minValue=0.001, maxValue=20.0,
                            fieldMinValue=0.001, fieldMaxValue=999.0,
                            field=True, precision=3, enable=is_x,
                            columnWidth2=[60, 100])
        cmds.setParent("..")

    cmds.separator(height=6, style="in")
    cmds.text(label="BS = 1.0 when translate reaches the Travel Limit value.",
              align="center", font="smallPlainLabelFont", height=18)
    cmds.text(label="Invert: positive translate drives negative weight, and vice versa.",
              align="center", font="smallPlainLabelFont", height=18)
    cmds.text(label="Travel Limit is added as a keyable attr on the control.",
              align="center", font="smallPlainLabelFont", height=18)
    cmds.setParent("..")
    cmds.setParent("..")
    cmds.separator(height=6, style="none")

    cmds.rowLayout(numberOfColumns=2, columnWidth2=[240, 240],
                   columnAlign2=["center", "center"], adjustableColumn=True)
    cmds.button(label="Connect BlendShape", height=38,
                backgroundColor=[0.2, 0.5, 0.2], command=_on_connect)
    cmds.button(label="Disconnect Target", height=38,
                backgroundColor=[0.55, 0.2, 0.2], command=_on_disconnect)
    cmds.setParent("..")

    cmds.separator(height=8, style="in")
    cmds.text("statusText", label="Status:  —",
              align="left", font="smallPlainLabelFont", height=20)
    cmds.separator(height=8, style="none")

    cmds.showWindow(win)
    if bs_nodes and get_blendshape_targets(bs_nodes[0]):
        _refresh_status()



# LAUNCH TOOL UI

create_ui()
