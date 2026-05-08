# maya-blendshape-control-system-tool-v1
Procedural Maya rigging tool that automates control to blendshape hookups using utility node networks.  

Supports: 
~ bidirectional control mapping
~ -1 to 1 remapping
~ adjustable limit range/multiplier with attribute
~ inversion support
~ automatic opposite target pairing
~ non-destructive node-based workflows

Directions to use:
1. Copy and paste code from file/blendShapeHookupTool.py into script editor in Maya on python tab
2. For quicker use and sanity - highlight and drag script into rigging toolbox
3. Tool UI appears after running code or clicking toolbox icon
4. Select control and click "Load Selected"
5. Under BlendShape, select desired blend shape node, and desired blend shape target
6. Select blendshape 0 to 1 or -1 to 1 if applicable (blend shape target range as control translation is altered)
7. Next stage: Axis, direction, and travel limit
  - Select axis(s) to utilize (x, y, z)
  - Select positive or negative movement to be evaluted; invert allows user to read opposite movement if applicable or wanted
  - Travel limit is the value of a control's movement along an axes in world space. Creates attribute in channel box.
    Example: "Cheek Puff bs target" reaches 0 to 1 once control reaches specified target range 3 along Z.
8. Click "Connect BlendShape" and done!
9. "Disconnect Target" option can be used to break blend shape targets to a control
  - Cut all incoming connections to a blendshape target
  - Automated node editor -> break connection

