# Sliding Dovetail Joint Manager v0.8.0
# Author: Chris Adcock
# Alibre Script / IronPython 2.7
#
# CLEAN REWRITE after coordinate-system diagnostic.
#
# CAD construction:
#   Each side gets exactly:
#       1 reference plane normal to the selected seam
#       1 dovetail profile sketch
#       1 simple extrude boss/cut along the seam
#       1 optional longitudinal corner-fillet feature
#
# This is the natural CAD construction for a sliding longitudinal dovetail:
# the trapezoid is the cross-section; the seam is the extrusion direction.
#
# Critically, ALL geometry is created in each component's LOCAL coordinate
# system. Assembly coordinates are used only to communicate the two selected
# reference edges between the assembled occurrences.
#
# User selections:
#   Male Part
#   Female Part
#   Shared Seam Edge
#   Shared Start Reference Edge
#
# References are frozen after first capture so subsequent dimension updates
# are immune to Edge<> renumbering caused by the generated feature.
#
# The Start Reference Edge only chooses which seam endpoint is START and
# supplies the through-thickness direction. It does NOT have to be re-found
# as identical topology in both parts.
#
# End condition:
#   Full Seam (default)
#   Distance
#
# Clearance:
#   "Mating Surface Clearance" is a TRUE normal offset of the female cavity:
#     - each dovetail flank is offset normal to itself
#     - the female head/depth face is offset by the same clearance
#   Male and female flanks therefore remain exactly parallel.
#
# Units: INCHES
#
# Corner blends:
#   - optional constant-radius blends are applied to the four longitudinal
#     dovetail edges after the boss/cut is created
#   - female blend radius = male blend radius + mating clearance, preserving
#     the same normal-offset logic through the rounded corners
#
# v1.04: exact persistent reference highlighting for Edit/Remove.
# New joints save the selected seam/start edge keys and limit face key.
# No endpoint matching or whole-component highlight fallback.
# A UI timer keeps native highlighting active until cleared or closed.
# Geometry construction, defaults and the existing manager UI are unchanged.

from __future__ import division
from math import *
import re
import sys
from System.Reflection import BindingFlags
import json
import os
from datetime import datetime
import System
from System import Enum, Array, Object


# Geometry and saved joint data remain inch based. The form converts values
# to the active document's File Properties > Units > Length Unit setting.
SESSION_UNITS = None
DISPLAY_UNIT = 'in'
DISPLAY_UNITS_PER_INCH = 1.0
try:
    SESSION_UNITS = Units.Current
except:
    pass
try:
    # This is the document display setting, not the script engine's Units.Current.
    _DocumentUnitName = str(DT_Session.DesignProperties.LengthDisplayUnits).lower()
    if 'millimeter' in _DocumentUnitName:
        DISPLAY_UNIT, DISPLAY_UNITS_PER_INCH = 'mm', 25.4
    elif 'centimeter' in _DocumentUnitName:
        DISPLAY_UNIT, DISPLAY_UNITS_PER_INCH = 'cm', 2.54
    elif 'meter' in _DocumentUnitName:
        DISPLAY_UNIT, DISPLAY_UNITS_PER_INCH = 'm', 0.0254
    elif 'feet' in _DocumentUnitName or 'foot' in _DocumentUnitName:
        DISPLAY_UNIT, DISPLAY_UNITS_PER_INCH = 'ft', 1.0 / 12.0
    elif 'inch' in _DocumentUnitName:
        DISPLAY_UNIT, DISPLAY_UNITS_PER_INCH = 'in', 1.0
except:
    pass
try:
    Units.Current = UnitTypes.Inches
except:
    pass
SESSION_DISPLAY_UNIT = DISPLAY_UNIT
UNIT_SCALE = {'in': 1.0, 'mm': 25.4, 'cm': 2.54, 'm': 0.0254, 'ft': 1.0 / 12.0}
UNIT_LABELS = {'in': 'Inches (in)', 'mm': 'Millimeters (mm)',
               'cm': 'Centimeters (cm)', 'm': 'Meters (m)', 'ft': 'Feet (ft)'}
def UnitChoices():
    return ['Use Alibre session (%s)' % SESSION_DISPLAY_UNIT,
            UNIT_LABELS['in'], UNIT_LABELS['mm'], UNIT_LABELS['cm'], UNIT_LABELS['m'], UNIT_LABELS['ft']]

def SetDisplayUnitChoice(Choice):
    global DISPLAY_UNIT, DISPLAY_UNITS_PER_INCH
    Choice = str(Choice)
    if Choice.startswith('Use Alibre session'):
        Key = SESSION_DISPLAY_UNIT
    elif '(mm)' in Choice:
        Key = 'mm'
    elif '(cm)' in Choice:
        Key = 'cm'
    elif '(m)' in Choice:
        Key = 'm'
    elif '(ft)' in Choice:
        Key = 'ft'
    else:
        Key = 'in'
    DISPLAY_UNIT = Key
    DISPLAY_UNITS_PER_INCH = UNIT_SCALE[Key]

def ToDisplayLength(Inches): return float(Inches) * DISPLAY_UNITS_PER_INCH
def ToInternalLength(DisplayValue): return float(DisplayValue) / DISPLAY_UNITS_PER_INCH
def SetLengthInput(Index, Inches): Win.SetInputValue(Index, ToDisplayLength(Inches))
def GetLengthInput(Index): return ToInternalLength(float(Win.GetInputValue(Index)))
def DisplayLengthText(Inches, Decimals=4): return ('%.*f' % (Decimals, ToDisplayLength(Inches))).rstrip('0').rstrip('.')

def ChangeDisplayUnit(Choice):
    # Convert the values currently visible in the form back to inches using
    # the old display unit, then redraw them using the newly selected unit.
    Values = {}
    for Index in [IDX_HEAD, IDX_DEPTH, IDX_CLEARANCE, IDX_DISTANCE, IDX_MINWALL, IDX_BLEND]:
        try:
            Values[Index] = GetLengthInput(Index)
        except:
            pass
    SetDisplayUnitChoice(Choice)
    Win.SetLengthUnit(DISPLAY_UNIT)
    for Index, Inches in Values.items():
        SetLengthInput(Index, Inches)
    UpdateLengthModeInputs()
    UpdateMaxHeadDisplay()
    Win.InfoDialog('Display units set to %s.' % DISPLAY_UNIT)

def RestoreSessionUnits():
    if SESSION_UNITS is None: return
    try: Units.Current = SESSION_UNITS
    except: pass
SCRIPT_NAME = 'Sliding Dovetail Joint Manager v0.8.0'
REF_TOL = 0.005
PROPERTY_NAME = '3DP_DT_DATA'
REGISTRY_SCHEMA = 4

# Factory defaults used by the live UtilityDialog. Keep these names local to
# the manager because the add-on host executes this file directly and does not
# import dt_defaults.py as a module.
DEFAULT_HEAD_WIDTH = 0.750
DEFAULT_DEPTH = 0.250
DEFAULT_ANGLE = 60.0
DEFAULT_CLEARANCE = 0.006
DEFAULT_DISTANCE = 2.000
DEFAULT_MIN_WALL = 0.060
DEFAULT_BLEND_RADIUS = 0.030

try:
    import dt_defaults
except:
    dt_defaults = None

def DefaultsPath():
    Root = os.environ.get('APPDATA', '')
    return os.path.join(Root, 'SlidingDovetailJointManager', 'defaults.json')

def LoadUserDefaults():
    if dt_defaults is None:
        return {'head_width': DEFAULT_HEAD_WIDTH, 'depth': DEFAULT_DEPTH,
                'angle': DEFAULT_ANGLE, 'clearance': DEFAULT_CLEARANCE,
                'distance': DEFAULT_DISTANCE, 'min_wall': DEFAULT_MIN_WALL,
                'blend_radius': DEFAULT_BLEND_RADIUS, 'length_mode': 0}
    Values, Warning = dt_defaults.load(DefaultsPath())
    if Warning:
        print Warning
    return Values

USER_DEFAULTS = LoadUserDefaults()

# =============================================================================
# Vector math
# =============================================================================

def V2Add(A,B):
    return [A[0]+B[0], A[1]+B[1]]

def V2Sub(A,B):
    return [A[0]-B[0], A[1]-B[1]]

def V2Scale(A,S):
    return [A[0]*S, A[1]*S]

def V2Dot(A,B):
    return A[0]*B[0] + A[1]*B[1]

def V2Len(A):
    return sqrt(V2Dot(A,A))

def V2Unit(A):
    L = V2Len(A)
    if L < 1.0e-9:
        raise Exception('Zero-length 2D vector.')
    return [A[0]/L, A[1]/L]

def V3Sub(A,B):
    return [A[0]-B[0], A[1]-B[1], A[2]-B[2]]

def V3Dot(A,B):
    return A[0]*B[0] + A[1]*B[1] + A[2]*B[2]

def V3Len(A):
    return sqrt(V3Dot(A,A))

def V3Unit(A):
    L = V3Len(A)
    if L < 1.0e-9:
        raise Exception('Zero-length 3D vector.')
    return [A[0]/L, A[1]/L, A[2]/L]

def Dist3(A,B):
    return V3Len(V3Sub(A,B))


# =============================================================================
# Alibre coordinate helpers
# =============================================================================

def OccLabel(P):
    try:
        return P.Name
    except:
        return str(P)

def SourceLabel(P):
    return re.sub(r'<\d+>$', '', OccLabel(P)).strip()

def PartToAssy(P, X):
    Q = P.PartPointtoAssemblyPoint(X)
    return [Q[0], Q[1], Q[2]]

def AssyToPart(P, X):
    Q = P.AssemblyPointtoPartPoint(X)
    return [Q[0], Q[1], Q[2]]

def EdgeLocalPoints(E):
    V = E.GetVertices()
    return [
        [V[0].X, V[0].Y, V[0].Z],
        [V[1].X, V[1].Y, V[1].Z]
    ]

def ResolveSelectedEdgeOccurrence(E, MalePart, FemalePart, Label):
    """
    Diagnostic testing proved:
      Edge.GetVertices() -> source-part LOCAL coordinates.

    Edge.GetPart() is used only to identify the owner.
    The explicitly-selected AssembledPart is used for the transform.
    """
    Owner = E.GetPart()
    OwnerLabel = OccLabel(Owner)
    OwnerSource = SourceLabel(Owner)

    Matches = []

    for P in [MalePart, FemalePart]:
        if OwnerLabel == OccLabel(P):
            Matches.append(P)

    if len(Matches) == 0:
        for P in [MalePart, FemalePart]:
            if OwnerSource == SourceLabel(P):
                Matches.append(P)

    if len(Matches) != 1:
        raise Exception(
            '%s: could not uniquely map selected edge owner "%s" to '
            'one selected assembly occurrence.'
            % (Label, OwnerLabel)
        )

    return Matches[0]

def SelectedEdgeToAssembly(E, MalePart, FemalePart, Label):
    P = ResolveSelectedEdgeOccurrence(E, MalePart, FemalePart, Label)
    L = EdgeLocalPoints(E)

    A0 = PartToAssy(P, L[0])
    A1 = PartToAssy(P, L[1])

    RawLength = Dist3(L[0], L[1])
    AssyLength = Dist3(A0, A1)
    API_Length = float(E.Length)

    print '%s owner: %s' % (Label, OccLabel(P))
    print '%s lengths API/raw/assembly: %.9f / %.9f / %.9f in' % (
        Label, API_Length, RawLength, AssyLength
    )

    if abs(API_Length-RawLength) > 0.000001:
        raise Exception('%s: raw edge length disagrees with Alibre Edge.Length.' % Label)

    if abs(API_Length-AssyLength) > 0.000001:
        raise Exception('%s: assembly transform changed edge length.' % Label)

    return [A0, A1]

def OrderSeamByStartReference(Seam, StartRef):
    Candidates = []

    for I in range(2):
        for J in range(2):
            Candidates.append((Dist3(Seam[I], StartRef[J]), I))

    Candidates.sort(key=lambda X:X[0])
    D, I = Candidates[0]

    print 'Start-reference to seam endpoint distance: %.9f in' % D

    if D > REF_TOL:
        raise Exception(
            'Start Reference Edge does not meet the Shared Seam Edge.\n'
            'Nearest endpoint separation: %.6f in.' % D
        )

    return [Seam[I], Seam[1-I]]


# =============================================================================
# Dovetail geometry
# =============================================================================

def MaleGeometry(HeadWidth, Depth, AngleDeg):
    """
    Angle is measured between flank and root/base line.
    """
    T = radians(AngleDeg)
    RootWidth = HeadWidth - 2.0*Depth/tan(T)

    if RootWidth <= 0:
        raise Exception(
            'Invalid male dovetail proportions.\n'
            'Head Width / Depth / Flank Angle produce a zero or negative root.'
        )

    return RootWidth, HeadWidth, Depth

def FemaleGeometry(HeadWidth, Depth, AngleDeg, Clearance):
    """
    True geometric offset of the three mating surfaces:
      - both sloped flanks offset normal by Clearance
      - deepest/head face offset by Clearance

    Male right flank:
        x = r + y*cot(theta)

    Offset flank:
        x = r + y*cot(theta) + Clearance*csc(theta)

    At female depth D+Clearance:
        x = h + Clearance*(cot(theta)+csc(theta))

    Therefore:
        FemaleRoot = MaleRoot + 2*C*csc(theta)
        FemaleDepth = MaleDepth + C
        FemaleHead = MaleHead + 2*C*(cot(theta)+csc(theta))
    """
    MR, MH, MD = MaleGeometry(HeadWidth, Depth, AngleDeg)

    T = radians(AngleDeg)
    S = sin(T)

    if abs(S) < 1.0e-9:
        raise Exception('Invalid flank angle for female clearance offset.')

    Csc = 1.0/S
    Cot = 1.0/tan(T)

    FR = MR + 2.0*Clearance*Csc
    FD = MD + Clearance
    FH = MH + 2.0*Clearance*(Cot + Csc)

    # Hard parallel-flank check.
    MaleSlope = (MH-MR)/(2.0*MD)
    FemaleSlope = (FH-FR)/(2.0*FD)

    print 'Flank slopes male/female: %.12f / %.12f' % (
        MaleSlope, FemaleSlope
    )

    if abs(MaleSlope-FemaleSlope) > 1.0e-10:
        raise Exception(
            'Internal geometry error: female and male dovetail flanks are not parallel.'
        )

    return FR, FH, FD

def MapPoint(S, P):
    UV = S.GlobaltoPoint(P[0], P[1], P[2])
    return [UV[0], UV[1]]

def ProjectVectorToSketch(S, Origin3, VectorEnd3):
    O = MapPoint(S, Origin3)
    E = MapPoint(S, VectorEnd3)
    return V2Sub(E,O)

def _CCWAngleDeg(C, A, B):
    """
    CCW angle from radius C->A to radius C->B, in [0, 360).
    """
    A0 = atan2(A[1]-C[1], A[0]-C[0])
    A1 = atan2(B[1]-C[1], B[0]-C[0])
    D = (A1-A0) * 180.0/pi

    while D < 0:
        D += 360.0

    while D >= 360.0:
        D -= 360.0

    return D


def _MinorArc(S, C, A, B, Radius, Label):
    """
    Add the short CCW arc between A and B around C.
    Alibre's AddArcCenterStartEnd() is CCW-only, so endpoint order is chosen
    explicitly to guarantee the minor arc.
    """
    CCW = _CCWAngleDeg(C, A, B)

    if CCW <= 180.0:
        Start = A
        End = B
        Sweep = CCW
    else:
        Start = B
        End = A
        Sweep = 360.0 - CCW

    print '  %s: radius=%.4f sweep=%.3f deg' % (
        Label, Radius, Sweep
    )

    return S.AddArcCenterStartEnd(
        C[0], C[1],
        Start[0], Start[1],
        End[0], End[1],
        False
    )


def _InternalCorner(Prev, Cur, Next, Radius):
    """
    Conventional fillet INSIDE the sharp trapezoid corner.
    Used at the two dovetail HEAD corners.
    """
    A = V2Unit(V2Sub(Prev, Cur))
    B = V2Unit(V2Sub(Next, Cur))

    Dot = max(-1.0, min(1.0, V2Dot(A, B)))
    Theta = acos(Dot)

    if Theta <= 1.0e-8 or abs(pi-Theta) <= 1.0e-8:
        raise Exception('Degenerate dovetail corner cannot be blended.')

    T = Radius / tan(Theta/2.0)
    Bis = V2Unit(V2Add(A, B))
    CD = Radius / sin(Theta/2.0)

    return {
        'prev': V2Add(Cur, V2Scale(A, T)),
        'next': V2Add(Cur, V2Scale(B, T)),
        'center': V2Add(Cur, V2Scale(Bis, CD)),
        'trim': T
    }


def _ExternalRootCorner(Cur, BaseOutDir, FlankDir, Radius):
    """
    Re-entrant ROOT fillet.

    The important distinction from alpha 0.36 is that the root fillet is NOT
    between the trapezoid's center root segment and the flank. In the finished
    dovetail, the body surface continues OUTWARD from the root. Therefore the
    tangent rays are:

        root -> outward along the panel surface
        root -> up the dovetail flank

    This places the circular blend OUTSIDE the sharp trapezoid, exactly like a
    native fillet on the longitudinal re-entrant root edge.
    """
    A = V2Unit(BaseOutDir)
    B = V2Unit(FlankDir)

    Dot = max(-1.0, min(1.0, V2Dot(A, B)))
    Theta = acos(Dot)

    if Theta <= 1.0e-8 or abs(pi-Theta) <= 1.0e-8:
        raise Exception('Degenerate dovetail root cannot be blended.')

    T = Radius / tan(Theta/2.0)
    Bis = V2Unit(V2Add(A, B))
    CD = Radius / sin(Theta/2.0)

    return {
        'base': V2Add(Cur, V2Scale(A, T)),
        'flank': V2Add(Cur, V2Scale(B, T)),
        'center': V2Add(Cur, V2Scale(Bis, CD)),
        'trim': T
    }


def AddTrapezoid(S, Mid, U, Vdir, RootWidth, HeadWidth, Depth,
                 RootRadius=0.0, HeadRadius=0.0):
    """
    Build the dovetail section with the SAME geometry as filleting the four
    longitudinal solid edges:

      * root corners are RE-ENTRANT blends, tangent to the panel surface
        continuing outward from each root and to the flank;
      * head corners are conventional external/convex fillets inside the sharp
        trapezoid.

    This is intentionally not a generic "rounded trapezoid".
    """
    RL = V2Add(Mid, V2Scale(U, -RootWidth/2.0))
    RR = V2Add(Mid, V2Scale(U,  RootWidth/2.0))

    HM = V2Add(Mid, V2Scale(Vdir, Depth))
    HL = V2Add(HM, V2Scale(U, -HeadWidth/2.0))
    HR = V2Add(HM, V2Scale(U,  HeadWidth/2.0))

    Figures = []

    # Exact original alpha-0.30 section when blends are disabled.
    if RootRadius <= 1.0e-12 and HeadRadius <= 1.0e-12:
        Figures.append(S.AddLine(RL[0],RL[1],RR[0],RR[1],False))
        Figures.append(S.AddLine(RR[0],RR[1],HR[0],HR[1],False))
        Figures.append(S.AddLine(HR[0],HR[1],HL[0],HL[1],False))
        Figures.append(S.AddLine(HL[0],HL[1],RL[0],RL[1],False))
        return Figures

    # Root blends use the OUTWARD panel-surface rays, not the root segment
    # between RL and RR.
    RightFlank = V2Unit(V2Sub(HR, RR))
    LeftFlank  = V2Unit(V2Sub(HL, RL))

    RRoot = None
    LRoot = None

    if RootRadius > 1.0e-12:
        RRoot = _ExternalRootCorner(
            RR, U, RightFlank, RootRadius
        )
        LRoot = _ExternalRootCorner(
            RL, V2Scale(U, -1.0), LeftFlank, RootRadius
        )

    # Head blends are ordinary internal fillets of the sharp trapezoid.
    RHead = None
    LHead = None

    if HeadRadius > 1.0e-12:
        RHead = _InternalCorner(RR, HR, HL, HeadRadius)
        LHead = _InternalCorner(HR, HL, RL, HeadRadius)

    # Resolve tangent points, falling back to sharp vertices where a radius is
    # disabled.
    BaseL = LRoot['base'] if LRoot is not None else RL
    BaseR = RRoot['base'] if RRoot is not None else RR

    RFlank0 = RRoot['flank'] if RRoot is not None else RR
    RFlank1 = RHead['prev'] if RHead is not None else HR

    HeadR = RHead['next'] if RHead is not None else HR
    HeadL = LHead['prev'] if LHead is not None else HL

    LFlank1 = LHead['next'] if LHead is not None else HL
    LFlank0 = LRoot['flank'] if LRoot is not None else RL

    # Sanity: no radius may consume an entire flank/head.
    if V2Len(V2Sub(RFlank1, RFlank0)) <= 1.0e-6:
        raise Exception('Corner Blend Radius is too large for the right flank.')

    if V2Len(V2Sub(LFlank1, LFlank0)) <= 1.0e-6:
        raise Exception('Corner Blend Radius is too large for the left flank.')

    if V2Len(V2Sub(HeadL, HeadR)) <= 1.0e-6:
        raise Exception('Corner Blend Radius is too large for the dovetail head.')

    # Closed profile, walking CCW:
    # extended panel-surface root -> right root arc -> right flank ->
    # right head arc -> head -> left head arc -> left flank ->
    # left root arc -> extended panel-surface root.
    Figures.append(
        S.AddLine(BaseL[0], BaseL[1], BaseR[0], BaseR[1], False)
    )

    if RRoot is not None:
        Figures.append(
            _MinorArc(
                S, RRoot['center'], RRoot['base'], RRoot['flank'],
                RootRadius, 'right root blend'
            )
        )

    Figures.append(
        S.AddLine(
            RFlank0[0], RFlank0[1],
            RFlank1[0], RFlank1[1],
            False
        )
    )

    if RHead is not None:
        Figures.append(
            _MinorArc(
                S, RHead['center'], RHead['prev'], RHead['next'],
                HeadRadius, 'right head blend'
            )
        )

    Figures.append(
        S.AddLine(HeadR[0], HeadR[1], HeadL[0], HeadL[1], False)
    )

    if LHead is not None:
        Figures.append(
            _MinorArc(
                S, LHead['center'], LHead['prev'], LHead['next'],
                HeadRadius, 'left head blend'
            )
        )

    Figures.append(
        S.AddLine(
            LFlank1[0], LFlank1[1],
            LFlank0[0], LFlank0[1],
            False
        )
    )

    if LRoot is not None:
        Figures.append(
            _MinorArc(
                S, LRoot['center'], LRoot['flank'], LRoot['base'],
                RootRadius, 'left root blend'
            )
        )

    return Figures


def FixGeneratedSketch(S, Figures, Side):
    """
    Best-effort sketch hardening.

    The Alibre docs expose a Sketch.Constraints enum, but the user's IronPython
    host does not expose Constraints as a global and does not allow importing
    it from AlibreScript.API. Resolve it from the Sketch object at runtime.

    IMPORTANT: failure to resolve the enum must NEVER block dovetail creation.
    In that case the geometry is still created and a console warning is issued.
    """
    ConstraintEnum = None

    # The generated docs list "Constraints enum name (Sketch)", so first try
    # the enum through the live Sketch wrapper.
    try:
        ConstraintEnum = S.Constraints
    except:
        ConstraintEnum = None

    if ConstraintEnum is None:
        print '%s sketch hardening WARNING: Fix constraint enum is not exposed by this Alibre Script runtime. Sketch left unconstrained.' % Side
        return False

    try:
        FixValue = ConstraintEnum.Fix
    except:
        print '%s sketch hardening WARNING: Constraints.Fix is not exposed by this Alibre Script runtime. Sketch left unconstrained.' % Side
        return False

    Fixed = 0

    for Figure in Figures:
        if Figure is None:
            print '%s sketch hardening WARNING: null generated figure; sketch left partially unconstrained.' % Side
            continue

        try:
            Added = S.AddConstraint(Figure, FixValue)

            if Added:
                Fixed += 1
            else:
                print '%s sketch hardening WARNING: Fix constraint was rejected for one figure.' % Side
        except Exception as Ex:
            print '%s sketch hardening WARNING: %s' % (
                Side, str(Ex)
            )

    print '%s sketch hardened: %d of %d figure(s) fixed.' % (
        Side, Fixed, len(Figures)
    )

    return Fixed == len(Figures)


# =============================================================================
# Part geometry / cleanup
# =============================================================================

def JointTag(JointID):
    return 'DT%03d' % int(JointID)

def FeatureName(JointID, Side):
    return '%s %s Extrude' % (JointTag(JointID), Side)

def BlendFeatureName(JointID, Side):
    return '%s %s Corner Blends' % (JointTag(JointID), Side)

def SketchName(JointID, Side):
    return '%s %s Profile' % (JointTag(JointID), Side)

def PlaneName(JointID, Side):
    return '%s %s Start Plane' % (JointTag(JointID), Side)

def _RemoveRetrievedAll(P, GetMethodName, RemoveMethodName, Name, MaxAttempts=16):
    """
    Drain duplicate reference objects safely.

    We only repeat when GetPlane/GetPoint positively proves an object exists.
    This avoids the alpha-0.27 failure where RemoveFeature() on a missing name
    did not throw, causing hundreds of pointless removal calls.
    """
    Count = 0

    try:
        GetFunc = getattr(P, GetMethodName)
        RemoveFunc = getattr(P, RemoveMethodName)
    except:
        return Count

    for Attempt in range(MaxAttempts):
        try:
            Obj = GetFunc(Name)
        except:
            break

        if Obj is None:
            break

        try:
            RemoveFunc(Obj)
            Count += 1
        except:
            break

    return Count


def Cleanup(P, JointID, Side, IncludeLegacy=False):
    """
    SAFE cleanup for one DT### side.

    Ordinary feature/sketch removal is attempted ONCE.
    Reference planes/points may legitimately have duplicate same-named crumbs,
    so only those are drained repeatedly, and only after GetPlane/GetPoint
    confirms each object exists.
    """
    FName = FeatureName(JointID, Side)
    SName = SketchName(JointID, Side)
    PName = PlaneName(JointID, Side)

    Removed = {
        'features': 0,
        'sketches': 0,
        'planes': 0,
        'points': 0
    }

    # Child blend must be removed before its parent extrude.
    try:
        P.RemoveFeature(BlendFeatureName(JointID, Side))
        Removed['features'] += 1
    except:
        pass

    # Solid feature: ONE attempt only.
    try:
        P.RemoveFeature(FName)
        Removed['features'] += 1
    except:
        pass

    # Sketch: ONE attempt only.
    try:
        P.RemoveSketch(SName)
        Removed['sketches'] += 1
    except:
        pass

    # Plane: drain only while GetPlane proves one exists.
    Removed['planes'] += _RemoveRetrievedAll(
        P, 'GetPlane', 'RemovePlane', PName
    )

    # AddPlane(normal, point) support points.
    for I in [1, 2, 3]:
        PointName = '%s Point %d' % (PName, I)
        Removed['points'] += _RemoveRetrievedAll(
            P, 'GetPoint', 'RemovePoint', PointName
        )

    if IncludeLegacy:
        # Non-manager alpha names: single feature/sketch attempts.
        LegacyFeatures = [
            'DT %s Extrude' % Side,
            'DT Alpha %s' % Side,
            'DT1 %s' % Side,
            'DT1 %s Sweep' % Side
        ]

        LegacySketches = [
            'DT %s Profile' % Side,
            'DT Alpha %s Profile' % Side,
            'DT1 %s Profile' % Side,
            'DT1 %s Path' % Side
        ]

        LegacyPlanes = [
            'DT %s Start Plane' % Side,
            'DT1 %s Plane' % Side
        ]

        for N in LegacyFeatures:
            try:
                P.RemoveFeature(N)
                Removed['features'] += 1
            except:
                pass

        for N in LegacySketches:
            try:
                P.RemoveSketch(N)
                Removed['sketches'] += 1
            except:
                pass

        for N in LegacyPlanes:
            Removed['planes'] += _RemoveRetrievedAll(
                P, 'GetPlane', 'RemovePlane', N
            )

            for I in [1, 2, 3]:
                PN = '%s Point %d' % (N, I)
                Removed['points'] += _RemoveRetrievedAll(
                    P, 'GetPoint', 'RemovePoint', PN
                )

    try:
        P.Regenerate()
    except:
        pass

    print '%s %s cleanup: features=%d sketches=%d planes=%d points=%d' % (
        JointTag(JointID),
        Side,
        Removed['features'],
        Removed['sketches'],
        Removed['planes'],
        Removed['points']
    )

    return Removed

def PartCentroidAssembly(P):
    Verts = P.GetAssemblyVertices()

    if Verts is None or len(Verts) == 0:
        raise Exception('%s: unable to obtain component vertices.' % OccLabel(P))

    N = float(len(Verts))
    return [
        sum([X[0] for X in Verts])/N,
        sum([X[1] for X in Verts])/N,
        sum([X[2] for X in Verts])/N
    ]


# =============================================================================
# Build one clean longitudinal feature
# =============================================================================

def PreflightSide(P, Side, IsMale,
                  SeamStartAssy, SeamEndAssy, ThicknessRefAssy,
                  HeadWidth, Depth, AngleDeg, Clearance, MinWall):

    LocalStart = AssyToPart(P, SeamStartAssy)
    LocalEnd = AssyToPart(P, SeamEndAssy)

    LocalT0 = AssyToPart(P, ThicknessRefAssy[0])
    LocalT1 = AssyToPart(P, ThicknessRefAssy[1])

    SeamVector = V3Sub(LocalEnd, LocalStart)
    SeamLength = V3Len(SeamVector)

    if SeamLength <= 0.000001:
        raise Exception('%s: local seam vector is invalid.' % Side)

    Thickness = Dist3(LocalT0, LocalT1)

    if Thickness <= 0.000001:
        raise Exception('%s: selected thickness reference has invalid length.' % Side)


    if IsMale:
        Root, Head, D = MaleGeometry(HeadWidth, Depth, AngleDeg)
    else:
        Root, Head, D = FemaleGeometry(
            HeadWidth, Depth, AngleDeg, Clearance
        )

    Wall = (Thickness-Head)/2.0

    print '%s preflight: seam %.4f, thickness %.4f, head %.4f, wall %.4f in/side' % (
        Side, SeamLength, Thickness, Head, Wall
    )

    if Wall < MinWall:
        raise Exception(
            '%s violates minimum thickness wall.\n\n'
            'Thickness: %.4f in\n'
            'Profile head: %.4f in\n'
            'Remaining wall: %.4f in/side\n'
            'Required wall: %.4f in'
            % (Side, Thickness, Head, Wall, MinWall)
        )

    return {
        'start': LocalStart,
        'end': LocalEnd,
        'seam_vector': SeamVector,
        'thickness_p0': LocalT0,
        'thickness_p1': LocalT1,
        'thickness': Thickness,
        'root': Root,
        'head': Head,
        'depth': D
    }

def EdgeLocalEndpoints(E):
    V = E.GetVertices()
    return [
        [float(V[0].X), float(V[0].Y), float(V[0].Z)],
        [float(V[1].X), float(V[1].Y), float(V[1].Z)]
    ]


def FindProfileLongitudinalEdges(P, S, SeamVector, Length, ProfileCorners):
    """
    Find the four edges generated by extruding the four trapezoid corners.

    This is geometry-based, not topology-name-based:
      1. edge must be parallel to the seam/extrusion vector;
      2. edge length must match the requested joint length;
      3. when projected into the cross-section sketch, the edge must land on
         one of the four persisted trapezoid corner locations.
    """
    D = V3Unit(SeamVector)
    CornerTol = 0.002
    LengthTol = 0.002
    ParallelTol = 0.9999

    Matches = []
    UsedCorner = set()

    try:
        Edges = list(P.Edges)
    except:
        Edges = []

    for E in Edges:
        try:
            EP = EdgeLocalEndpoints(E)
            EV = V3Sub(EP[1], EP[0])
            EL = V3Len(EV)
            if EL <= 0.000001:
                continue

            ED = V3Scale(EV, 1.0/EL)
            if abs(V3Dot(ED, D)) < ParallelTol:
                continue

            if abs(EL-Length) > LengthTol:
                continue

            # Either endpoint projects to the same cross-section location for
            # a line parallel to the plane normal. Use endpoint zero.
            UV = MapPoint(S, EP[0])

            BestI = None
            BestErr = None
            for I in range(len(ProfileCorners)):
                Err = V2Len(V2Sub(UV, ProfileCorners[I]))
                if BestErr is None or Err < BestErr:
                    BestErr = Err
                    BestI = I

            if BestErr is not None and BestErr <= CornerTol and BestI not in UsedCorner:
                Matches.append(E)
                UsedCorner.add(BestI)
                print '  blend edge match: %s -> corner %d, error %.6f in' % (
                    str(getattr(E, 'Name', '<unnamed>')), BestI+1, BestErr
                )
        except:
            pass

    return Matches


def AddCornerBlends(P, S, JointID, Side, IsMale, Geo, Length,
                    ProfileCorners, MaleBlendRadius, Clearance):
    if MaleBlendRadius <= 0:
        return

    # The female cavity is the normal-offset mate of the male profile. For a
    # circular corner, offsetting outward by C increases its radius by C.
    Radius = MaleBlendRadius if IsMale else MaleBlendRadius + Clearance

    if Radius <= 0:
        return

    Edges = FindProfileLongitudinalEdges(
        P, S, Geo['seam_vector'], Length, ProfileCorners
    )

    if len(Edges) != 4:
        raise Exception(
            '%s corner-blend edge identification found %d of 4 required '
            'longitudinal dovetail edges. No blend was committed.'
            % (Side, len(Edges))
        )

    print '%s corner blends: radius %.4f in on 4 longitudinal edges' % (
        Side, Radius
    )

    try:
        P.AddFillet(
            BlendFeatureName(JointID, Side),
            Edges,
            Radius,
            True
        )
    except Exception as Ex:
        raise Exception(
            '%s corner blend failed at radius %.4f in.\n\n%s'
            % (Side, Radius, str(Ex))
        )

    try:
        P.Regenerate()
    except:
        pass


def BuildSide(P, JointID, Side, IsMale, Geo, LengthMode, Length, LimitTarget, BlendRadius, Clearance):
    """
    Clean CAD:
      datum plane at seam start, normal = seam vector
      sketch on datum plane
      simple extrude along plane normal
    """
    Plane = P.AddPlane(
        PlaneName(JointID, Side),
        Geo['seam_vector'],
        Geo['start']
    )

    S = P.AddSketch(SketchName(JointID, Side), Plane)

    # Map the physical through-thickness reference line directly into this
    # cross-section sketch.
    A2 = MapPoint(S, Geo['thickness_p0'])
    B2 = MapPoint(S, Geo['thickness_p1'])

    U = V2Unit(V2Sub(B2,A2))
    Mid = [
        (A2[0]+B2[0])/2.0,
        (A2[1]+B2[1])/2.0
    ]

    # Determine panel-interior side using the actual component centroid.
    CentroidAssy = PartCentroidAssembly(P)
    CentroidLocal = AssyToPart(P, CentroidAssy)
    C2 = MapPoint(S, CentroidLocal)

    Perp = [-U[1], U[0]]

    if V2Dot(V2Sub(C2,Mid),Perp) < 0:
        Perp = V2Scale(Perp,-1.0)

    # Female cavity goes INTO its own part.
    # Male boss goes OUT of its part, across the assembly seam.
    ProfileDirection = Perp if not IsMale else V2Scale(Perp,-1.0)

    # Corner-radius treatment:
    #
    # ROOTS:
    #   Use the SAME root radius on male and female. The female sharp-root
    #   location is already displaced by the straight-flank clearance
    #   construction (FR > MR). Using a smaller female root radius causes its
    #   tangent point to walk back toward the male root and can cancel/reverse
    #   that clearance -- the "pinch" seen in alpha 0.37.
    #
    # HEAD:
    #   Keep the female head radius enlarged by clearance. This produced the
    #   correct visible external/head relationship in alpha 0.37.
    #
    # A zero requested blend remains exactly zero on both parts.
    RootRadius = 0.0
    HeadRadius = 0.0

    if BlendRadius > 1.0e-12:
        RootRadius = BlendRadius

        if IsMale:
            HeadRadius = BlendRadius
        else:
            HeadRadius = BlendRadius + Clearance

    GeneratedFigures = AddTrapezoid(
        S,
        Mid,
        U,
        ProfileDirection,
        Geo['root'],
        Geo['head'],
        Geo['depth'],
        RootRadius,
        HeadRadius
    )

    FixGeneratedSketch(S, GeneratedFigures, Side)

    print '%s sketch blends: root=%.4f in, head=%.4f in' % (
        Side, RootRadius, HeadRadius
    )

    # This follows Alibre's official "cylinder between two points" construction:
    # plane normal = end-start, then Reverse=False extrudes toward end.
    Reverse = False

    if LengthMode == 'up_to_geometry':
        if LimitTarget is None: raise Exception('%s build requires a valid Limit Geometry Face.' % Side)
        RawAsm=_RawAssembly(); DetailOcc=P.GetMappedOccurrence(RawAsm)
        if DetailOcc is None or DetailOcc.DesignSession is None: raise Exception('%s raw part session could not be resolved.' % Side)
        RP=DetailOcc.DesignSession; RS=RP.Sketches.Item(SketchName(JointID,Side)); Fs=RP.Features
        MN='AddExtrudedBoss' if IsMale else 'AddExtrudedCutout'
        Ms=[M for M in Fs.GetType().GetMethods() if M.Name==MN and len(M.GetParameters())==15]
        if len(Ms)!=1: raise Exception('%s expected one 15-argument %s overload; found %d.' % (Side,MN,len(Ms)))
        M=Ms[0]; Ps=M.GetParameters()
        EC=_EnumValue(Ps[2].ParameterType,['AD_TO_GEOMETRY','TO_GEOMETRY'])
        DN=_EnumValue(Ps[6].ParameterType,['AD_ALONG_NORMAL','ALONG_NORMAL','NORMAL'])
        TO,TF=LimitTarget
        Args=Array[Object]([RS,0.0,EC,TO,TF,0.0,DN,None,None,False,0.0,False,FeatureName(JointID,Side),'',''])
        try: RF=M.Invoke(Fs,Args)
        except Exception as Ex:
            Inner=''
            try:
                if Ex.InnerException is not None: Inner='\n\n'+str(Ex.InnerException)
            except: pass
            raise Exception('%s Up To Geometry extrusion failed.\n\n%s%s' % (Side,str(Ex),Inner))
        if RF is None: raise Exception('%s Up To Geometry extrusion returned no feature.' % Side)
        try:
            PX=RF.EndCondition
            if PX is None or PX.Target is None or PX.Occurrence is None: raise Exception('target proxy missing')
        except Exception as Ex: raise Exception('%s Up To Geometry target was not retained.\n\n%s' % (Side,str(Ex)))
        print '%s build: associative Up To Geometry' % Side
    else:
        print '%s build: plane-normal extrusion %.4f in, reverse=False' % (
            Side, Length
        )

        if IsMale:
            P.AddExtrudeBoss(
                FeatureName(JointID, Side),
                S,
                Length,
                Reverse
            )
        else:
            P.AddExtrudeCut(
                FeatureName(JointID, Side),
                S,
                Length,
                Reverse
            )

    try:
        P.Regenerate()
    except:
        pass

    # Corner blends are already part of the driving profile sketch.


# =============================================================================
# Persistent registry
# =============================================================================

def ReadPropertyRaw():
    try:
        V = A.GetCustomProperty(PROPERTY_NAME)
        if V is None:
            return ''
        return str(V)
    except:
        return ''

def EmptyRegistry():
    return {
        'schema': REGISTRY_SCHEMA,
        'type': '3dp_dovetail_registry',
        'next_id': 1,
        'joints': {}
    }

def LoadRegistry():
    Raw = ReadPropertyRaw()

    if Raw == '':
        return EmptyRegistry()

    try:
        R = json.loads(Raw)
    except Exception as Ex:
        raise Exception(
            '%s contains data that is not valid JSON.\n%s'
            % (PROPERTY_NAME, str(Ex))
        )

    # Do not silently reinterpret the old POC payload.
    if R.get('type', '') != '3dp_dovetail_registry':
        raise Exception(
            '%s exists, but it is not a DT joint registry.\n\n'
            'Clear the old proof-of-concept value or replace it with a blank '
            'property before using the manager.'
            % PROPERTY_NAME
        )

    if 'joints' not in R:
        R['joints'] = {}
    if 'next_id' not in R:
        R['next_id'] = 1

    return R

def SaveRegistry(R):
    Raw = json.dumps(R, sort_keys=True, separators=(',', ':'))

    A.SetCustomProperty(PROPERTY_NAME, Raw)
    Verify = ReadPropertyRaw()

    if Verify != Raw:
        raise Exception(
            'Could not persist DT registry.\n\n'
            'Confirm that the assembly already contains a custom file property '
            'named exactly %s.'
            % PROPERTY_NAME
        )

def JointKey(JointID):
    return JointTag(JointID)

def JointChoiceLabel(Record):
    J = Record.get('joint_id', 'DT???')
    M = Record.get('male_part_occurrence', '?')
    F = Record.get('female_part_occurrence', '?')
    return '%s | %s -> %s' % (J, M, F)

def BuildJointChoices(R):
    Items = []

    for K in sorted(R.get('joints', {}).keys()):
        Items.append(JointChoiceLabel(R['joints'][K]))

    if len(Items) == 0:
        Items.append('(No existing DT joints)')

    return Items

def JointIDFromChoice(Value, Choices):
    # Alibre StringList may return index or selected text.
    if isinstance(Value, int):
        if Value < 0 or Value >= len(Choices):
            raise Exception('Invalid Existing Joint selection.')
        Label = Choices[Value]
    else:
        Label = str(Value)

    if Label.startswith('(No existing'):
        raise Exception('No existing DT joints are stored in this assembly.')

    # First token is DT###
    Token = Label.split('|')[0].strip()

    if not Token.startswith('DT'):
        raise Exception('Could not determine joint ID from selection: %s' % Label)

    try:
        return int(Token[2:])
    except:
        raise Exception('Could not parse joint number from selection: %s' % Label)

def NextJointID(R):
    J = int(R.get('next_id', 1))

    while JointKey(J) in R['joints']:
        J += 1

    return J

def RecordFeatureNames(JointID):
    return {
        'male': {
            'plane': PlaneName(JointID, 'Male'),
            'profile': SketchName(JointID, 'Male'),
            'extrude': FeatureName(JointID, 'Male'),
            'blend': BlendFeatureName(JointID, 'Male')
        },
        'female': {
            'plane': PlaneName(JointID, 'Female'),
            'profile': SketchName(JointID, 'Female'),
            'extrude': FeatureName(JointID, 'Female'),
            'blend': BlendFeatureName(JointID, 'Female')
        }
    }

def MakeJointRecord(JointID, MalePart, FemalePart,
                    OrderedSeam, StartRefAssy,
                    LengthMode, HeadWidth, Depth, AngleDeg,
                    Clearance, DistanceLength, LimitPlaneName,
                    MinWall, BlendRadius):
    SeamLength = Dist3(OrderedSeam[0], OrderedSeam[1])

    if LengthMode == 'full_seam':
        EffectiveLength = SeamLength
    elif LengthMode == 'distance':
        EffectiveLength = DistanceLength
    else:
        # Actual ToGeometry depth is controlled by the assembly plane and is
        # intentionally not reduced to a stale numeric value in the registry.
        EffectiveLength = None

    return {
        'joint_id': JointKey(JointID),
        'joint_number': int(JointID),
        'male_part_occurrence': OccLabel(MalePart),
        'female_part_occurrence': OccLabel(FemalePart),
        'seam_start_assy': list(OrderedSeam[0]),
        'seam_end_assy': list(OrderedSeam[1]),
        'start_ref_assy': [
            list(StartRefAssy[0]),
            list(StartRefAssy[1])
        ],
        'end_condition': str(LengthMode),
        'distance_length_in': float(DistanceLength),
        'limit_target': LimitPlaneName if LengthMode == 'up_to_geometry' else None,
        'effective_length_in': None if EffectiveLength is None else float(EffectiveLength),
        'head_width_in': float(HeadWidth),
        'depth_in': float(Depth),
        'flank_angle_deg': float(AngleDeg),
        'clearance_in': float(Clearance),
        'minimum_wall_in': float(MinWall),
        'corner_blend_radius_in': float(BlendRadius),
        'features': RecordFeatureNames(JointID),
        'updated_timestamp': datetime.now().isoformat()
    }

def GetRecord(R, JointID):
    K = JointKey(JointID)
    if K not in R['joints']:
        raise Exception(
            'Joint %s was not found in the assembly registry.'
            % K
        )
    return R['joints'][K]

def ValidateSelectedPartsAgainstRecord(MalePart, FemalePart, Record):
    EM = Record.get('male_part_occurrence', '')
    EF = Record.get('female_part_occurrence', '')

    if OccLabel(MalePart) != EM:
        raise Exception(
            'Selected Male Part does not match %s.\n\nStored: %s\nSelected: %s'
            % (Record.get('joint_id','joint'), EM, OccLabel(MalePart))
        )

    if OccLabel(FemalePart) != EF:
        raise Exception(
            'Selected Female Part does not match %s.\n\nStored: %s\nSelected: %s'
            % (Record.get('joint_id','joint'), EF, OccLabel(FemalePart))
        )

def ReferencesFromRecord(Record):
    return (
        [
            list(Record['seam_start_assy']),
            list(Record['seam_end_assy'])
        ],
        [
            list(Record['start_ref_assy'][0]),
            list(Record['start_ref_assy'][1])
        ]
    )

def ResolvePartsFromRecord(Record):
    """
    Edit/Remove should not require the user to reselect the two components.
    Assembly.GetPart(name) is the documented lookup for an assembled part
    occurrence, and the occurrence names are persisted in the joint record.
    """
    MaleName = Record.get('male_part_occurrence', '')
    FemaleName = Record.get('female_part_occurrence', '')

    if MaleName == '' or FemaleName == '':
        raise Exception('Stored joint record is missing component occurrence names.')

    try:
        MalePart = A.GetPart(MaleName)
    except Exception as Ex:
        raise Exception(
            'Could not find stored Male Part occurrence "%s".\n%s'
            % (MaleName, str(Ex))
        )

    try:
        FemalePart = A.GetPart(FemaleName)
    except Exception as Ex:
        raise Exception(
            'Could not find stored Female Part occurrence "%s".\n%s'
            % (FemaleName, str(Ex))
        )

    if MalePart is None or FemalePart is None:
        raise Exception(
            'One or both stored component occurrences are no longer present '
            'in the assembly.'
        )

    return MalePart, FemalePart

def PrintJointSummary(Record):
    print '------------------------------------------------------------'
    print 'Stored joint: %s' % Record.get('joint_id','?')
    print 'Male: %s' % Record.get('male_part_occurrence','?')
    print 'Female: %s' % Record.get('female_part_occurrence','?')
    print 'End condition: %s' % Record.get('end_condition','?')
    print 'Head Width: %.6f in' % float(Record.get('head_width_in',0))
    print 'Depth: %.6f in' % float(Record.get('depth_in',0))
    print 'Angle: %.6f deg' % float(Record.get('flank_angle_deg',0))
    print 'Clearance: %.6f in' % float(Record.get('clearance_in',0))
    print 'Minimum Wall: %.6f in' % float(Record.get('minimum_wall_in',0))
    print 'Corner Blend Radius: %.6f in' % float(Record.get('corner_blend_radius_in',0))
    print 'Limit Geometry: %s' % str(Record.get('limit_target',''))
    print '------------------------------------------------------------'


# =============================================================================
# Geometry transaction
# =============================================================================

def _PrivateField(Obj, Name):
    Flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic
    F = Obj.GetType().GetField(Name, Flags)
    return None if F is None else F.GetValue(Obj)

def _EnumValue(T, Names):
    All = list(Enum.GetNames(T))
    for Want in Names:
        for N in All:
            if N.upper() == Want.upper(): return Enum.Parse(T,N)
    for Want in Names:
        for N in All:
            if Want.upper() in N.upper(): return Enum.Parse(T,N)
    raise Exception('Required enum value not found in %s.' % str(T.FullName))

def _RawAssembly():
    R = _PrivateField(A, '_Assembly')
    if R is None: raise Exception('Could not resolve the underlying assembly session.')
    return R

def _RawFace(F):
    # Script topology wrappers are not consistent about their private member
    # names.  Edge wrappers commonly expose _Edge; Face wrappers in current
    # builds may use a different field/property.  Resolve by preferred names
    # first, then by the raw topology contract (persistent Key + Type) and a
    # runtime type name containing "Face".
    Flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic
    T = F.GetType()

    for Name in ['_Face', 'Face', '_ADFace', 'ADFace', '_Topology', 'Topology']:
        try:
            Field=T.GetField(Name,Flags)
            if Field is not None:
                V=Field.GetValue(F)
                if V is not None and V is not F and hasattr(V,'Key') and hasattr(V,'Type'):
                    return V
        except: pass
        try:
            Prop=T.GetProperty(Name,Flags)
            if Prop is not None:
                V=Prop.GetValue(F,None)
                if V is not None and V is not F and hasattr(V,'Key') and hasattr(V,'Type'):
                    return V
        except: pass

    for Field in T.GetFields(Flags):
        try:
            V=Field.GetValue(F)
            if V is None or V is F: continue
            TN=str(V.GetType().FullName)
            if 'face' in TN.lower() and hasattr(V,'Key') and hasattr(V,'Type'):
                return V
        except: pass

    for Prop in T.GetProperties(Flags):
        try:
            V=Prop.GetValue(F,None)
            if V is None or V is F: continue
            TN=str(V.GetType().FullName)
            if 'face' in TN.lower() and hasattr(V,'Key') and hasattr(V,'Type'):
                return V
        except: pass

    raise Exception('Could not resolve the selected face through the Alibre API.')

def CaptureLimitTarget(F):
    if F is None or str(F).strip() == '': raise Exception('Select a Limit Geometry Face for Up To Geometry.')
    Owner=F.GetPart(); OwnerName=OccLabel(Owner)
    try: OwnerPart=A.GetPart(OwnerName)
    except: OwnerPart=Owner
    RawAsm=_RawAssembly()
    try: Occ=OwnerPart.GetMappedOccurrence(RawAsm)
    except: Occ=None
    if Occ is None: raise Exception('Could not resolve the occurrence owning the Limit Geometry Face.')
    RF=_RawFace(F)
    Spec = {'occurrence':str(Occ.Name),'face_key':[int(X) for X in RF.Key]}
    if not Spec['face_key']: raise Exception('The selected limit face has no persistent key.')
    ResolveLimitTarget(Spec)
    return Spec

def ResolveLimitTarget(Spec):
    if not isinstance(Spec,dict): raise Exception('Stored Up To Geometry reference is missing.')
    N=str(Spec.get('occurrence','')); K=Spec.get('face_key',None)
    if N=='' or K is None: raise Exception('Stored Up To Geometry reference is incomplete.')
    P=A.GetPart(N); Occ=P.GetMappedOccurrence(_RawAssembly())
    if Occ is None or Occ.DesignSession is None: raise Exception('Stored limit-geometry occurrence could not be resolved.')
    RP=Occ.DesignSession
    Ms=[M for M in RP.GetType().GetMethods() if M.Name=='BindKeyToItem' and len(M.GetParameters())==2]
    if len(Ms)<1: raise Exception('BindKeyToItem is unavailable.')
    M=Ms[0]; OT=_EnumValue(M.GetParameters()[1].ParameterType,['AD_TOPOLOGY'])
    Key=Array[System.Byte]([int(X) for X in K])
    RF=M.Invoke(RP,Array[Object]([Key,OT]))
    if RF is None: raise Exception('Stored Limit Geometry Face no longer exists. Reselect it while editing.')
    if str(RF.TopologyType) != 'AD_FACE':
        raise Exception('Stored limit reference did not resolve to a face.')
    return (Occ,RF)

# =============================================================================
# Native exact-reference highlighting and keeper (v1.04)
# =============================================================================

# Created lazily from a dialog callback, on the existing UI thread.
_HighlightTimer = None
_HighlightCollector = None
_HighlightSession = None
_HighlightBusy = False
_HighlightTickBusy = False


def _HighlightRoot():
    import AlibreScript
    return AlibreScript.API.Global.Root


def ClearJointHighlight():
    global _HighlightCollector, _HighlightSession
    Session = _HighlightSession
    # Drop cached proxies before clearing so a queued tick cannot restore them.
    _HighlightCollector = None
    _HighlightSession = None
    try:
        if _HighlightTimer is not None: _HighlightTimer.Stop()
    except Exception as Ex:
        print 'Joint highlight warning: timer stop: %s' % str(Ex)
    try:
        Root = _HighlightRoot()
        if Session is None: Session = _RawAssembly()
        Session.Highlight(Root.NewObjectCollector())
    except Exception as Ex:
        print 'Joint highlight warning: clear: %s' % str(Ex)


def _HighlightKeeperTick(Sender, Event):
    global _HighlightTickBusy
    if _HighlightBusy or _HighlightTickBusy or _HighlightCollector is None:
        return
    _HighlightTickBusy = True
    try:
        if CurrentOperation() not in ['Edit Existing', 'Remove Existing']:
            ClearJointHighlight()
            return
        # Do not apply this assembly's references to another active document.
        if _HighlightRoot().TopmostSession != _HighlightSession: return
        _HighlightSession.Highlight(_HighlightCollector)
    except Exception as Ex:
        # Stop on failure rather than repeatedly logging at timer frequency.
        ClearJointHighlight()
        print 'Joint highlight warning: keeper stopped: %s' % str(Ex)
    finally:
        _HighlightTickBusy = False


def _StartHighlightKeeper(Session, Collector):
    global _HighlightTimer, _HighlightCollector, _HighlightSession
    _HighlightSession = Session
    _HighlightCollector = Collector
    Session.Highlight(Collector)
    try:
        if _HighlightTimer is None:
            import clr
            clr.AddReference('System.Windows.Forms')
            from System.Windows.Forms import Timer
            _HighlightTimer = Timer()
            _HighlightTimer.Interval = 250
            _HighlightTimer.Tick += _HighlightKeeperTick
        _HighlightTimer.Start()
    except Exception as Ex:
        print 'Joint highlight warning: keeper unavailable: %s' % str(Ex)


def DisposeHighlightKeeper():
    global _HighlightTimer
    ClearJointHighlight()
    Timer = _HighlightTimer
    _HighlightTimer = None
    if Timer is not None:
        try:
            Timer.Tick -= _HighlightKeeperTick
            Timer.Dispose()
        except Exception as Ex:
            print 'Joint highlight warning: timer disposal: %s' % str(Ex)


def _RawEdge(E):
    Flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic
    T = E.GetType()
    for Name in ['_Edge', 'Edge', '_ADEdge', 'ADEdge', '_Topology', 'Topology']:
        for IsField in [True, False]:
            try:
                Member = T.GetField(Name, Flags) if IsField else T.GetProperty(Name, Flags)
                if Member is None: continue
                V = Member.GetValue(E) if IsField else Member.GetValue(E, None)
                if V is not None and V is not E and hasattr(V, 'Key') and hasattr(V, 'Type'):
                    return V
            except: pass
    for IsField in [True, False]:
        Members = T.GetFields(Flags) if IsField else T.GetProperties(Flags)
        for Member in Members:
            try:
                V = Member.GetValue(E) if IsField else Member.GetValue(E, None)
                if V is None or V is E: continue
                if 'edge' in str(V.GetType().FullName).lower() and hasattr(V, 'Key') and hasattr(V, 'Type'):
                    return V
            except: pass
    raise Exception('Could not resolve the reference edge through the Alibre API.')


def CaptureHighlightEdge(E, MalePart, FemalePart, Label):
    # Required for NEW joints; fail before geometry changes if exact references
    # cannot be saved. Existing records remain editable/removable without them.
    try:
        P = ResolveSelectedEdgeOccurrence(E, MalePart, FemalePart, Label)
        Occ = P.GetMappedOccurrence(_RawAssembly())
        if Occ is None or Occ.DesignSession is None:
            raise Exception('The selected edge occurrence could not be resolved.')
        RE = _RawEdge(E)
        Key = [int(X) for X in RE.Key]
        if not Key: raise Exception('The selected edge has no persistent key.')
        Spec = {'occurrence': OccLabel(P), 'edge_key': Key}
        # Verify the key can be bound in this occurrence before accepting it.
        if _BindHighlightEdge(Spec, _RawAssembly()) is None:
            raise Exception('The selected edge could not be bound to its occurrence.')
        return Spec
    except Exception as Ex:
        raise Exception('%s: could not save the exact reference. %s' % (Label, str(Ex)))


def _BindHighlightEdge(Spec, RawAsm):
    if not isinstance(Spec, dict) or not Spec.get('occurrence') or not Spec.get('edge_key'):
        raise Exception('No exact edge reference is stored for this joint.')
    P = A.GetPart(str(Spec['occurrence']))
    Occ = P.GetMappedOccurrence(RawAsm)
    if Occ is None or Occ.DesignSession is None:
        raise Exception('Stored reference occurrence is unavailable.')
    RP = Occ.DesignSession
    Ms = [M for M in RP.GetType().GetMethods() if M.Name == 'BindKeyToItem' and len(M.GetParameters()) == 2]
    if not Ms: raise Exception('BindKeyToItem is unavailable.')
    M = Ms[0]
    OT = _EnumValue(M.GetParameters()[1].ParameterType, ['AD_TOPOLOGY'])
    Key = Array[System.Byte]([int(X) for X in Spec['edge_key']])
    RE = M.Invoke(RP, Array[Object]([Key, OT]))
    if RE is None: raise Exception('Stored reference edge no longer exists.')
    if str(RE.TopologyType) != 'AD_EDGE':
        raise Exception('Stored reference did not resolve to an edge.')
    Proxy = RawAsm.NewTargetProxy(Occ, RE)
    if Proxy is None: raise Exception('Could not create the exact edge proxy.')
    return Proxy





def HighlightJointRecord(Record):
    ClearJointHighlight()
    if _HighlightBusy: return
    try:
        if CurrentOperation() not in ['Edit Existing', 'Remove Existing']: return
        Root = _HighlightRoot()
        RawAsm = _RawAssembly()
        Collector = Root.NewObjectCollector()
        Count = 0
        for Name, Label in [('seam_edge_target', 'Shared Seam Edge'),
                            ('start_edge_target', 'Shared Start Reference Edge')]:
            try:
                Collector.Add(_BindHighlightEdge(Record.get(Name), RawAsm))
                Count += 1
            except Exception as Ex:
                print 'Joint highlight warning: %s: %s' % (Label, str(Ex))
        if Record.get('end_condition') == 'up_to_geometry':
            try:
                Occ, RF = ResolveLimitTarget(Record.get('limit_target'))
                Proxy = RawAsm.NewTargetProxy(Occ, RF)
                if Proxy is None: raise Exception('Could not create the exact face proxy.')
                Collector.Add(Proxy)
                Count += 1
            except Exception as Ex:
                print 'Joint highlight warning: Limit Geometry Face: %s' % str(Ex)
        if Count:
            _StartHighlightKeeper(RawAsm, Collector)
    except Exception as Ex:
        ClearJointHighlight()
        print 'Joint highlight warning: %s' % str(Ex)


def HighlightSelectedJoint(Choice):
    try:
        R = LoadRegistry()
        J = JointIDFromChoice(Choice, ExistingJointChoices)
        HighlightJointRecord(GetRecord(R, J))
    except Exception as Ex:
        ClearJointHighlight()
        print 'Joint highlight warning: %s' % str(Ex)


def NormalizeLengthMode(Value):
    Modes=['full_seam','distance','up_to_geometry']
    if isinstance(Value,int):
        if Value<0 or Value>=len(Modes): raise Exception('Invalid Length Mode selection.')
        return Modes[Value]
    S=str(Value).strip().lower()
    D={'full seam':'full_seam','full_seam':'full_seam','distance':'distance','up to geometry':'up_to_geometry','up_to_geometry':'up_to_geometry'}
    if S in D: return D[S]
    raise Exception('Invalid Length Mode "%s".' % str(Value))

def ValidateNumericInputs(HeadWidth, Depth, AngleDeg,
                          Clearance, DistanceLength, MinWall, BlendRadius):
    if HeadWidth <= 0 or Depth <= 0:
        raise Exception('Head Width and Dovetail Depth must be greater than zero.')

    if AngleDeg <= 0 or AngleDeg >= 90:
        raise Exception('Flank Angle must be between 0 and 90 degrees.')

    if Clearance < 0 or MinWall < 0 or BlendRadius < 0:
        raise Exception('Clearance, Minimum Wall and Corner Blend Radius cannot be negative.')

    # Distance is validated against the active Length Mode in
    # BuildJointGeometry. Keeping this numeric field harmless while disabled
    # avoids blocking Full Seam / Up To Geometry edits.


def ValidateCommonInputs(MalePart, FemalePart,
                         HeadWidth, Depth, AngleDeg,
                         Clearance, DistanceLength, MinWall, BlendRadius):
    if MalePart is None or FemalePart is None:
        raise Exception('Select both Male Part and Female Part.')

    if OccLabel(MalePart) == OccLabel(FemalePart):
        raise Exception('Male and Female are the same assembly occurrence.')

    if SourceLabel(MalePart) == SourceLabel(FemalePart):
        raise Exception('Male and Female must be unique .AD_PRT files.')

    ValidateNumericInputs(
        HeadWidth, Depth, AngleDeg,
        Clearance, DistanceLength, MinWall, BlendRadius
    )


def BuildJointGeometry(JointID, MalePart, FemalePart,
                       OrderedSeam, StartRefAssy,
                       LengthMode, HeadWidth, Depth, AngleDeg,
                       Clearance, DistanceLength, LimitPlaneName,
                       MinWall, BlendRadius,
                       IncludeLegacy=False):
    SeamLength = Dist3(OrderedSeam[0], OrderedSeam[1])
    LengthMode = NormalizeLengthMode(LengthMode)
    LimitPlane = ResolveLimitTarget(LimitPlaneName) if LengthMode == 'up_to_geometry' else None

    if LengthMode == 'full_seam':
        Length = SeamLength
    elif LengthMode == 'distance':
        Length = float(DistanceLength)

        if Length <= 0:
            raise Exception('Distance Length must be greater than zero.')

        if Length > SeamLength + REF_TOL:
            raise Exception(
                'Requested distance %.4f in exceeds seam length %.4f in.'
                % (Length, SeamLength)
            )
    else:
        # ToGeometry owns the true termination depth. Length remains a harmless
        # reference value for profile-edge bookkeeping and diagnostics.
        Length = SeamLength

    # Preflight BEFORE deleting the current joint.
    MaleGeo = PreflightSide(
        MalePart, 'Male', True,
        OrderedSeam[0], OrderedSeam[1], StartRefAssy,
        HeadWidth, Depth, AngleDeg, Clearance, MinWall
    )

    FemaleGeo = PreflightSide(
        FemalePart, 'Female', False,
        OrderedSeam[0], OrderedSeam[1], StartRefAssy,
        HeadWidth, Depth, AngleDeg, Clearance, MinWall
    )

    Cleanup(MalePart, JointID, 'Male', IncludeLegacy)
    Cleanup(FemalePart, JointID, 'Female', IncludeLegacy)

    try:
        BuildSide(
            FemalePart, JointID, 'Female', False,
            FemaleGeo, LengthMode, Length, LimitPlane,
            BlendRadius, Clearance
        )

        BuildSide(
            MalePart, JointID, 'Male', True,
            MaleGeo, LengthMode, Length, LimitPlane,
            BlendRadius, Clearance
        )
    except:
        Cleanup(MalePart, JointID, 'Male', False)
        Cleanup(FemalePart, JointID, 'Female', False)
        raise

    return MaleGeo, FemaleGeo, (None if LengthMode == 'up_to_geometry' else Length)


# =============================================================================
# Manager operations
# Rebuild/Inspect helpers are retained internally for diagnostics but are no longer exposed in the normal UI.
# =============================================================================

def CreateNewJoint(MalePart, FemalePart,
                   SeamSelection, StartSelection,
                   LengthMode, HeadWidth, Depth, AngleDeg,
                   Clearance, DistanceLength, LimitPlaneName,
                   MinWall, BlendRadius):
    if SeamSelection is None:
        raise Exception('Select Shared Seam Edge.')
    if StartSelection is None:
        raise Exception('Select Shared Start Reference Edge.')

    R = LoadRegistry()
    JointID = NextJointID(R)

    SeamAssy = SelectedEdgeToAssembly(
        SeamSelection, MalePart, FemalePart, 'Shared Seam Edge'
    )
    StartRefAssy = SelectedEdgeToAssembly(
        StartSelection, MalePart, FemalePart, 'Start Reference Edge'
    )
    OrderedSeam = OrderSeamByStartReference(SeamAssy, StartRefAssy)
    SeamHighlight = CaptureHighlightEdge(SeamSelection, MalePart, FemalePart, 'Shared Seam Edge')
    StartHighlight = CaptureHighlightEdge(StartSelection, MalePart, FemalePart, 'Start Reference Edge')

    # Preserve the alpha-0.20 seam invariant.
    SeamLength = Dist3(OrderedSeam[0], OrderedSeam[1])
    if abs(SeamLength-float(SeamSelection.Length)) > 0.000001:
        raise Exception(
            'Internal coordinate error: transformed seam length does not '
            'match Alibre Edge.Length.'
        )

    MaleGeo, FemaleGeo, Length = BuildJointGeometry(
        JointID, MalePart, FemalePart,
        OrderedSeam, StartRefAssy,
        LengthMode, HeadWidth, Depth, AngleDeg,
        Clearance, DistanceLength, LimitPlaneName,
        MinWall, BlendRadius,
        JointID == 1
    )

    Record = MakeJointRecord(
        JointID, MalePart, FemalePart,
        OrderedSeam, StartRefAssy,
        LengthMode, HeadWidth, Depth, AngleDeg,
        Clearance, DistanceLength, LimitPlaneName,
        MinWall, BlendRadius
    )
    Record['created_timestamp'] = datetime.now().isoformat()
    Record['seam_edge_target'] = SeamHighlight
    Record['start_edge_target'] = StartHighlight

    R['joints'][JointKey(JointID)] = Record
    R['next_id'] = JointID + 1
    SaveRegistry(R)

    if Length is None:
        print '%s created and persisted | termination=Up To Geometry "%s"' % (
            JointKey(JointID), str(LimitPlaneName)
        )
    else:
        print '%s created and persisted | length=%.3f in' % (
            JointKey(JointID), Length
        )

def RebuildStoredJoint(JointID):
    R = LoadRegistry()
    Record = GetRecord(R, JointID)
    MalePart, FemalePart = ResolvePartsFromRecord(Record)
    PrintJointSummary(Record)

    OrderedSeam, StartRefAssy = ReferencesFromRecord(Record)

    LengthMode = Record.get('end_condition','full_seam')

    MaleGeo, FemaleGeo, Length = BuildJointGeometry(
        JointID, MalePart, FemalePart,
        OrderedSeam, StartRefAssy,
        LengthMode,
        float(Record['head_width_in']),
        float(Record['depth_in']),
        float(Record['flank_angle_deg']),
        float(Record['clearance_in']),
        float(Record['distance_length_in']),
        Record.get('limit_target', None),
        float(Record['minimum_wall_in']),
        float(Record.get('corner_blend_radius_in', 0.0)),
        False
    )

    Record['updated_timestamp'] = datetime.now().isoformat()
    Record['effective_length_in'] = Length
    R['joints'][JointKey(JointID)] = Record
    SaveRegistry(R)

    if Length is None:
        print '%s rebuilt from persistent definition | termination=Up To Geometry "%s"' % (
            JointKey(JointID), str(Record.get('limit_target',None))
        )
    else:
        print '%s rebuilt from persistent definition | length=%.3f in' % (
            JointKey(JointID), Length
        )

def EditStoredJoint(JointID,
                    LengthMode, HeadWidth, Depth, AngleDeg,
                    Clearance, DistanceLength, LimitPlaneName,
                    MinWall, BlendRadius):
    """
    Edit a persisted joint without requiring geometry reselection.

    Transaction behavior:
      - resolve parts/references from stored metadata;
      - attempt new geometry;
      - if the rebuild fails after old geometry was removed, automatically
        restore the previous persisted definition before reporting the error;
      - only write new metadata after successful geometry creation.
    """
    ValidateNumericInputs(
        HeadWidth, Depth, AngleDeg,
        Clearance, DistanceLength, MinWall, BlendRadius
    )

    R = LoadRegistry()
    Old = GetRecord(R, JointID)
    if NormalizeLengthMode(LengthMode) == 'up_to_geometry' and LimitPlaneName is None:
        LimitPlaneName = Old.get('limit_target', None)
    MalePart, FemalePart = ResolvePartsFromRecord(Old)
    OrderedSeam, StartRefAssy = ReferencesFromRecord(Old)

    OldLengthMode = Old.get('end_condition','full_seam')

    try:
        MaleGeo, FemaleGeo, Length = BuildJointGeometry(
            JointID, MalePart, FemalePart,
            OrderedSeam, StartRefAssy,
            LengthMode, HeadWidth, Depth, AngleDeg,
            Clearance, DistanceLength, LimitPlaneName,
            MinWall, BlendRadius,
            False
        )
    except Exception as EditEx:
        print 'EDIT FAILED. Attempting automatic rollback of %s...' % JointKey(JointID)

        try:
            BuildJointGeometry(
                JointID, MalePart, FemalePart,
                OrderedSeam, StartRefAssy,
                OldLengthMode,
                float(Old['head_width_in']),
                float(Old['depth_in']),
                float(Old['flank_angle_deg']),
                float(Old['clearance_in']),
                float(Old['distance_length_in']),
                Old.get('limit_target', None),
                float(Old['minimum_wall_in']),
                float(Old.get('corner_blend_radius_in', 0.0)),
                False
            )
            print 'ROLLBACK SUCCEEDED. Previous joint geometry restored.'
        except Exception as RollbackEx:
            print 'ROLLBACK FAILED: %s' % str(RollbackEx)
            raise Exception(
                'Edit failed and automatic rollback also failed.\n\n'
                'Edit error:\n%s\n\nRollback error:\n%s'
                % (str(EditEx), str(RollbackEx))
            )

        raise Exception(
            'Edit was rejected and the previous joint was restored.\n\n%s'
            % str(EditEx)
        )

    New = MakeJointRecord(
        JointID, MalePart, FemalePart,
        OrderedSeam, StartRefAssy,
        LengthMode, HeadWidth, Depth, AngleDeg,
        Clearance, DistanceLength, LimitPlaneName,
        MinWall, BlendRadius
    )
    for Name in ['seam_edge_target', 'start_edge_target']:
        if Name in Old: New[Name] = Old[Name]
    New['created_timestamp'] = Old.get(
        'created_timestamp',
        datetime.now().isoformat()
    )

    R['joints'][JointKey(JointID)] = New
    SaveRegistry(R)

    if Length is None:
        print '%s updated and persisted | termination=Up To Geometry "%s"' % (
            JointKey(JointID), str(LimitPlaneName)
        )
    else:
        print '%s updated and persisted | length=%.3f in' % (
            JointKey(JointID), Length
        )


def RemoveStoredJoint(JointID):
    ClearJointHighlight()
    R = LoadRegistry()
    Record = GetRecord(R, JointID)
    MalePart, FemalePart = ResolvePartsFromRecord(Record)

    # POC proved RemoveFeature(name) survives save/close/reopen.
    print 'Removing complete feature/reference stack for %s...' % JointKey(JointID)

    MaleRemoved = Cleanup(MalePart, JointID, 'Male', False)
    FemaleRemoved = Cleanup(FemalePart, JointID, 'Female', False)

    print 'Complete duplicate-draining cleanup finished for both components.'

    del R['joints'][JointKey(JointID)]
    SaveRegistry(R)

    print '%s geometry and persistent definition removed.' % (
        JointKey(JointID)
    )

def InspectStoredJoint(JointID):
    R = LoadRegistry()
    Record = GetRecord(R, JointID)
    PrintJointSummary(Record)

    Win.InfoDialog(
        '%s found.\n\n'
        'Male: %s\n'
        'Female: %s\n'
        'Head Width: %.3f in\n'
        'Depth: %.3f in\n'
        'Angle: %.1f deg\n'
        'Clearance: %.4f in'
        % (
            Record['joint_id'],
            Record['male_part_occurrence'],
            Record['female_part_occurrence'],
            float(Record['head_width_in']),
            float(Record['depth_in']),
            float(Record['flank_angle_deg']),
            float(Record['clearance_in'])
        ),
        'Sliding Dovetail Joint Manager'
    )


# =============================================================================
# One-time legacy cleanup -- explicit IDs only
# =============================================================================

def ParseLegacyIDs(Text):
    S = str(Text).strip()

    if S == '':
        raise Exception(
            'Enter the legacy DT numbers to purge, for example: 1,2,3'
        )

    IDs = []

    for Token in S.replace(';', ',').split(','):
        T = Token.strip().upper()

        if T.startswith('DT'):
            T = T[2:]

        if T == '':
            continue

        try:
            J = int(T)
        except:
            raise Exception(
                'Could not parse legacy DT ID "%s". Use a list such as 1,2,3.'
                % Token
            )

        if J < 1 or J > 9999:
            raise Exception('Legacy DT ID %d is outside the allowed range.' % J)

        if J not in IDs:
            IDs.append(J)

    if len(IDs) == 0:
        raise Exception('No legacy DT IDs were supplied.')

    return IDs


def PurgeLegacyDebris(MalePart, FemalePart, LegacyText):
    """
    One-time maintenance only.

    We intentionally DO NOT scan hundreds of hypothetical DT numbers.
    The user supplies the orphan IDs visible in the Design Explorer.

    Registered joints are protected even if accidentally listed.
    """
    if MalePart is None or FemalePart is None:
        raise Exception(
            'Select the two parts containing the historical DT debris.'
        )

    IDs = ParseLegacyIDs(LegacyText)
    R = LoadRegistry()

    Protected = set()
    for K in R.get('joints', {}).keys():
        try:
            if K.startswith('DT'):
                Protected.add(int(K[2:]))
        except:
            pass

    ToPurge = [J for J in IDs if J not in Protected]
    Skipped = [J for J in IDs if J in Protected]

    if len(ToPurge) == 0:
        raise Exception(
            'Every requested DT ID is still registered. Nothing was purged.'
        )

    print '============================================================'
    print 'SAFE LEGACY PURGE'
    print 'Requested IDs: %s' % str(IDs)
    print 'Protected/skipped: %s' % str(Skipped)
    print 'Purging: %s' % str(ToPurge)

    Total = {
        'features': 0,
        'sketches': 0,
        'planes': 0,
        'points': 0
    }

    for JointID in ToPurge:
        for P in [MalePart, FemalePart]:
            # Early alpha builds sometimes put the wrong side label in a part.
            for Side in ['Male', 'Female']:
                Removed = Cleanup(P, JointID, Side, False)

                for Key in Total.keys():
                    Total[Key] += Removed.get(Key, 0)

    print 'PURGE TOTAL: features=%d sketches=%d planes=%d points=%d' % (
        Total['features'],
        Total['sketches'],
        Total['planes'],
        Total['points']
    )
    print '============================================================'

    Win.InfoDialog(
        'Legacy cleanup complete.\n\n'
        'Purged IDs: %s\n'
        'Protected IDs skipped: %s\n\n'
        'Features: %d\n'
        'Sketches: %d\n'
        'Planes: %d\n'
        'Points: %d'
        % (
            str(ToPurge),
            str(Skipped),
            Total['features'],
            Total['sketches'],
            Total['planes'],
            Total['points']
        ),
        'Sliding Dovetail Joint Manager'
    )


# =============================================================================
# UI design-limit helpers
# =============================================================================

def MaxNominalMaleHead(Thickness, AngleDeg, Clearance, MinWall):
    """
    Maximum nominal MALE head width allowed by both parts.

    Male requirement:
        Head <= Thickness - 2*MinWall

    Female cavity head is larger than nominal male head by the true normal
    clearance offset already used in FemaleGeometry():

        Delta = 2*C*(cot(theta) + csc(theta))

    Therefore the female side usually governs when Clearance > 0.
    """
    if Thickness is None:
        return None

    T = float(Thickness)
    A = float(AngleDeg)
    C = float(Clearance)
    W = float(MinWall)

    if T <= 0 or A <= 0 or A >= 90 or C < 0 or W < 0:
        return None

    R = radians(A)
    DeltaFemale = 2.0*C*(1.0/tan(R) + 1.0/sin(R))

    MaleLimit = T - 2.0*W
    FemaleLimit = T - 2.0*W - DeltaFemale

    return min(MaleLimit, FemaleLimit)


def ThicknessForCurrentUI(Operation):
    """
    For Create, use the selected start/thickness edge.
    For Edit, use the persisted start-reference length.
    """
    try:
        if Operation == 'Create New':
            E = _CapturedCreateSelections.get('start')
            if E is None or isinstance(E, basestring) or not hasattr(E, 'Length'):
                return None
            return float(E.Length)

        if Operation == 'Edit Existing':
            Choice = Win.GetInputValue(IDX_EXISTING)
            R = LoadRegistry()
            J = JointIDFromChoice(Choice, ExistingJointChoices)
            Rec = GetRecord(R, J)
            Ref = Rec.get('start_ref_assy', None)

            if Ref is None or len(Ref) != 2:
                return None
            try:
                return Dist3(Ref[0], Ref[1])
            except:
                return None

    except:
        return None

    return None


def CurrentOperation():
    V = Win.GetInputValue(IDX_OPERATION)
    Ops = ['Create New', 'Edit Existing', 'Remove Existing']

    if isinstance(V, int):
        if V < 0 or V >= len(Ops):
            return ''
        return Ops[V]

    Operation = str(V)
    return {'Create New Joint': 'Create New',
            'Edit Existing Joint': 'Edit Existing',
            'Remove Existing Joint': 'Remove Existing'}.get(Operation, Operation)


def UpdateMaxHeadDisplay():
    Operation = CurrentOperation()

    if Operation != 'Create New' and Operation != 'Edit Existing':
        Win.SetInputValue(IDX_MAXHEAD, '')
        return

    Thickness = ThicknessForCurrentUI(Operation)

    try:
        AngleDeg = float(Win.GetInputValue(IDX_ANGLE))
        Clearance = GetLengthInput(IDX_CLEARANCE)
        MinWall = GetLengthInput(IDX_MINWALL)
    except:
        Win.SetInputValue(IDX_MAXHEAD, '')
        return

    MaxHead = MaxNominalMaleHead(
        Thickness,
        AngleDeg,
        Clearance,
        MinWall
    )

    if MaxHead is None:
        Win.SetInputValue(IDX_MAXHEAD, 'Select start edge')
    elif MaxHead <= 0:
        Win.SetInputValue(IDX_MAXHEAD, 'No valid width')
    else:
        Win.SetInputValue(IDX_MAXHEAD, DisplayLengthText(MaxHead))


def UpdateLengthModeInputs():
    Operation = CurrentOperation()

    if Operation != 'Create New' and Operation != 'Edit Existing':
        Win.DisableInput(IDX_DISTANCE)
        Win.DisableInput(IDX_LIMITPLANE)
        return

    try:
        Mode = NormalizeLengthMode(Win.GetInputValue(IDX_LENGTHMODE))
    except:
        Mode = 'full_seam'

    if Mode == 'distance':
        Win.EnableInput(IDX_DISTANCE)
        Win.DisableInput(IDX_LIMITPLANE)
    elif Mode == 'up_to_geometry':
        Win.DisableInput(IDX_DISTANCE)
        Win.EnableInput(IDX_LIMITPLANE)
    else:
        Win.DisableInput(IDX_DISTANCE)
        Win.DisableInput(IDX_LIMITPLANE)


# =============================================================================
# Live manager UI helpers
# =============================================================================

IDX_OPERATION = 0
IDX_CAPTURE = 1
IDX_EXISTING = 2
IDX_MALE = 3
IDX_FEMALE = 4
IDX_SEAM = 5
IDX_START = 6
IDX_LENGTHMODE = 7
IDX_LIMITPLANE = 8
IDX_HEAD = 9
IDX_DEPTH = 10
IDX_ANGLE = 11
IDX_CLEARANCE = 12
IDX_DISTANCE = 13
IDX_MINWALL = 14
IDX_BLEND = 15
IDX_MAXHEAD = 16
IDX_SAVEDEFAULTS = 17

# Add-on Create New capture state.  Alibre Script's native picker controls are
# host-owned and cannot return selections to an externally hosted dialog.  The
# add-on instead reads the active assembly selection proxy directly.
_CapturedCreateSelections = {'male': None, 'female': None, 'seam': None, 'start': None, 'limit': None}
_CaptureBusy = False

# The add-on reads the selection synchronously when the user chooses one of
# these actions.  This avoids relying on a form timer after the dialog is open.
_CAPTURE_CHOICES = [
    'Save current workspace selection as...',
    'Save current selection as Male Part',
    'Save current selection as Female Part',
    'Save current selection as Shared Seam Edge',
    'Save current selection as Shared Start Reference Edge',
    'Save current selection as Limit Geometry Face'
]
_CAPTURE_KEYS = [None, 'male', 'female', 'seam', 'start', 'limit']


def _RawTopologyKey(Value):
    try:
        return [int(X) for X in Value.Key]
    except:
        return []


def _CapturedPart(Occurrence):
    if Occurrence is None:
        raise Exception('The selected item has no assembly occurrence.')
    try:
        return A.GetPart(str(Occurrence.Name))
    except:
        pass
    RawAsm = _RawAssembly()
    for P in A.Parts:
        try:
            Mapped = P.GetMappedOccurrence(RawAsm)
            if Mapped is Occurrence or str(Mapped.Name) == str(Occurrence.Name):
                return P
        except:
            pass
    raise Exception('Could not map the selected occurrence to an assembly part.')


def _CapturedTopology(Item, Kind):
    Occurrence = getattr(Item, 'Occurrence', None)
    Target = getattr(Item, 'Target', None)
    P = _CapturedPart(Occurrence)
    TargetKey = _RawTopologyKey(Target)

    # Native selection proxies do not always expose Edge<n>/Face<n> names, but
    # their persistent topology keys are available. Match the selected native
    # target to the Script wrapper by that key.
    if TargetKey:
        Candidates = P.GetEdges() if Kind == 'Edge' else P.GetFaces()
        for Candidate in Candidates:
            try:
                Raw = _RawEdge(Candidate) if Kind == 'Edge' else _RawFace(Candidate)
                if _RawTopologyKey(Raw) == TargetKey:
                    return Candidate
            except:
                pass

    Name = str(getattr(Target, 'Name', Target))
    Match = re.search(r'%s<\d+>' % Kind, Name)
    if Match is not None:
        Name = Match.group(0)
    try:
        return P.GetEdge(Name) if Kind == 'Edge' else P.GetFace(Name)
    except:
        raise Exception('The selected %s could not be mapped to the selected assembly occurrence.' % Kind.lower())


def _CaptureSelection(Key):
    Collector = DT_Root.TopmostSession.SelectedObjects
    if Collector.Count != 1:
        raise Exception('Select exactly one item in the workspace before saving the selection.')
    Item = Collector.Item(0)
    if Key == 'male' or Key == 'female':
        return _CapturedPart(getattr(Item, 'Occurrence', None))
    if Key == 'seam' or Key == 'start':
        return _CapturedTopology(Item, 'Edge')
    if Key == 'limit':
        return _CapturedTopology(Item, 'Face')
    raise Exception('Unknown capture target.')


def _CaptureDisplay(Key, Value):
    if Key == 'male': return OccLabel(Value)
    if Key == 'female': return OccLabel(Value)
    try:
        return '%s:%s' % (OccLabel(Value.GetPart()), str(Value.Name))
    except:
        return str(Value)


def _StartSelectionCapture(Value):
    global _CaptureBusy
    if _CaptureBusy:
        return False
    if isinstance(Value, basestring) and str(Value) in _CAPTURE_KEYS:
        Key = str(Value)
    else:
        try:
            Index = int(Value) if not isinstance(Value, basestring) else _CAPTURE_CHOICES.index(str(Value))
        except:
            Index = 0
        Key = _CAPTURE_KEYS[Index] if Index >= 0 and Index < len(_CAPTURE_KEYS) else None
    if Key is None:
        return

    _CaptureBusy = True
    try:
        Operation = CurrentOperation()
        if Operation == 'Remove Existing' or (Operation == 'Edit Existing' and Key != 'limit'):
            raise Exception('Existing joints retain their saved geometry. Only the limit face can be replaced while editing.')
        Captured = _CaptureSelection(Key)
        _CapturedCreateSelections[Key] = Captured
        Field = {'male': IDX_MALE, 'female': IDX_FEMALE, 'seam': IDX_SEAM, 'start': IDX_START, 'limit': IDX_LIMITPLANE}[Key]
        Win.SetInputValue(Field, _CaptureDisplay(Key, Captured))
        Win.SetInputValue(IDX_CAPTURE, 0)
        Win.InfoDialog('Captured %s: %s' % (Key, _CaptureDisplay(Key, Captured)))
        if Key == 'start':
            UpdateMaxHeadDisplay()
        try: DT_Log('Captured %s: %s' % (Key, _CaptureDisplay(Key, Captured)))
        except: pass
        return True
    except Exception as Ex:
        Message = 'Could not capture %s. %s' % (Key, str(Ex))
        try: DT_Log(Message)
        except: pass
        Win.ErrorDialog(Message, 'Sliding Dovetail Joint Manager')
        try: Win.SetInputValue(IDX_CAPTURE, 0)
        except: pass
        return False
    finally:
        _CaptureBusy = False

def ResetCreateInputs():
    """
    After a successful Create New, return the dialog to the same clean/default
    state it had when first opened.

    The newly-created joint remains in the Existing Joint list, but all Create
    selections and editable values are reset so there is no accidental reuse
    of the previous joint definition.
    """
    # Clear geometry selections.
    for Key in _CapturedCreateSelections:
        _CapturedCreateSelections[Key] = None
    #
    # In Alibre's UtilityDialog, SetInputValue(index, None) does not repaint
    # geometry-picker controls back to blank after a selection has been made.
    # An empty string does clear the displayed/current picker value and leaves
    # the control ready for a new geometry selection.
    RestoreCreateCapturePrompts()

    # Restore the actual dialog defaults.
    Win.SetInputValue(IDX_LENGTHMODE, USER_DEFAULTS['length_mode'])
    SetLengthInput(IDX_HEAD, USER_DEFAULTS['head_width'])
    SetLengthInput(IDX_DEPTH, USER_DEFAULTS['depth'])
    Win.SetInputValue(IDX_ANGLE, USER_DEFAULTS['angle'])
    SetLengthInput(IDX_CLEARANCE, USER_DEFAULTS['clearance'])
    SetLengthInput(IDX_DISTANCE, USER_DEFAULTS['distance'])
    Win.SetInputValue(IDX_LIMITPLANE, '')
    SetLengthInput(IDX_MINWALL, USER_DEFAULTS['min_wall'])
    SetLengthInput(IDX_BLEND, USER_DEFAULTS['blend_radius'])

    # Derived display is undefined until a new start/reference edge is chosen.
    Win.SetInputValue(IDX_MAXHEAD, 'Select start edge')

    UpdateLengthModeInputs()
    UpdateMaxHeadDisplay()

    print 'Create-New inputs reset to defaults.'


def RefreshExistingJointList(PreferredJointID=None):
    global ExistingJointChoices

    R = LoadRegistry()
    ExistingJointChoices = BuildJointChoices(R)
    Win.SetStringList(IDX_EXISTING, ExistingJointChoices)

    Pick = 0

    if PreferredJointID is not None:
        Prefix = JointKey(PreferredJointID) + ' |'

        for I in range(len(ExistingJointChoices)):
            if ExistingJointChoices[I].startswith(Prefix):
                Pick = I
                break

    Win.SetInputValue(IDX_EXISTING, Pick)


def SetExistingJointControlForOperation(Operation):
    """
    Existing Joint is irrelevant while creating a new joint.

    Disable AND visually blank the dropdown in Create New. Restore the real
    registry list for operations that act on registered joints.

    """
    if Operation == 'Create New':
        Win.SetStringList(IDX_EXISTING, ['(Not used for Create New)'])
        Win.SetInputValue(IDX_EXISTING, 0)
        Win.DisableInput(IDX_EXISTING)

    elif Operation == 'Edit Existing' or Operation == 'Remove Existing':
        RefreshExistingJointList(None)
        Win.EnableInput(IDX_EXISTING)


def RestoreCreateCapturePrompts():
    """Restore the instructional text for a fresh Create New operation.

    UtilityDialog does not repaint a String input reliably when it is reset
    with None.  Use the same prompt values as the initial dialog instead of
    relying on the dialog to reconstruct them after Edit/Remove clears them.
    """
    Prompt = 'Not captured'
    Win.SetInputValue(IDX_MALE, Prompt)
    Win.SetInputValue(IDX_FEMALE, Prompt)
    Win.SetInputValue(IDX_SEAM, Prompt)
    Win.SetInputValue(IDX_START, Prompt)
    Win.SetInputValue(IDX_LIMITPLANE, Prompt)


def ApplyDefaultsToInputs(Values):
    Win.SetInputValue(IDX_LENGTHMODE, Values['length_mode'])
    SetLengthInput(IDX_HEAD, Values['head_width'])
    SetLengthInput(IDX_DEPTH, Values['depth'])
    Win.SetInputValue(IDX_ANGLE, Values['angle'])
    SetLengthInput(IDX_CLEARANCE, Values['clearance'])
    SetLengthInput(IDX_DISTANCE, Values['distance'])
    SetLengthInput(IDX_MINWALL, Values['min_wall'])
    SetLengthInput(IDX_BLEND, Values['blend_radius'])
    UpdateLengthModeInputs()
    UpdateMaxHeadDisplay()


def SaveCurrentDefaults():
    global USER_DEFAULTS
    if dt_defaults is None:
        raise Exception('The defaults preference module is unavailable.')
    Values = {
        'head_width': GetLengthInput(IDX_HEAD),
        'depth': GetLengthInput(IDX_DEPTH),
        'angle': float(Win.GetInputValue(IDX_ANGLE)),
        'clearance': GetLengthInput(IDX_CLEARANCE),
        'distance': GetLengthInput(IDX_DISTANCE),
        'min_wall': GetLengthInput(IDX_MINWALL),
        'blend_radius': GetLengthInput(IDX_BLEND),
        'length_mode': ['full_seam', 'distance', 'up_to_geometry'].index(NormalizeLengthMode(Win.GetInputValue(IDX_LENGTHMODE))),
    }
    USER_DEFAULTS = dt_defaults.save(DefaultsPath(), Values)


def HandleDefaultsAction(ActionValue):
    global USER_DEFAULTS
    Action = str(ActionValue)
    if Action == 'Save current values as defaults':
        SaveCurrentDefaults()
        print 'Saved Sliding Dovetail defaults.'
        Win.InfoDialog('Defaults saved for future Create New operations.')
    elif Action == 'Load saved defaults':
        USER_DEFAULTS = LoadUserDefaults()
        ApplyDefaultsToInputs(USER_DEFAULTS)
        Win.InfoDialog('Saved defaults loaded into the form.')
    elif Action == 'Restore factory defaults':
        USER_DEFAULTS = {'head_width': DEFAULT_HEAD_WIDTH, 'depth': DEFAULT_DEPTH,
                         'angle': DEFAULT_ANGLE, 'clearance': DEFAULT_CLEARANCE,
                         'distance': DEFAULT_DISTANCE, 'min_wall': DEFAULT_MIN_WALL,
                         'blend_radius': DEFAULT_BLEND_RADIUS, 'length_mode': 0}
        ApplyDefaultsToInputs(USER_DEFAULTS)
        Win.InfoDialog('Factory defaults restored in the form.')
    Win.SetInputValue(IDX_SAVEDEFAULTS, 0)


def LoadSelectedJointIntoUI(ChoiceValue):
    """
    Populate the editable fields from persistent metadata.
    No component/edge selection is required for Edit or Remove.
    """
    _CapturedCreateSelections['limit'] = None
    R = LoadRegistry()
    if not R.get('joints'):
        ClearJointHighlight()
        return
    JointID = JointIDFromChoice(ChoiceValue, ExistingJointChoices)
    Record = GetRecord(R, JointID)

    HighlightJointRecord(Record)

    Mode = Record.get('end_condition', 'full_seam')
    ModeIndex = 0

    if Mode == 'distance':
        ModeIndex = 1
    elif Mode == 'up_to_geometry':
        ModeIndex = 2

    Win.SetInputValue(IDX_LENGTHMODE, ModeIndex)
    SetLengthInput(IDX_HEAD, float(Record['head_width_in']))
    SetLengthInput(IDX_DEPTH, float(Record['depth_in']))
    Win.SetInputValue(IDX_ANGLE, float(Record['flank_angle_deg']))
    SetLengthInput(IDX_CLEARANCE, float(Record['clearance_in']))
    SetLengthInput(IDX_DISTANCE, float(Record['distance_length_in']))
    Win.SetInputValue(IDX_LIMITPLANE, '')
    SetLengthInput(IDX_MINWALL, float(Record['minimum_wall_in']))
    SetLengthInput(IDX_BLEND, float(Record.get('corner_blend_radius_in', 0.0)))

    UpdateLengthModeInputs()
    UpdateMaxHeadDisplay()

    print 'Loaded %s into Edit fields: head=%.4f depth=%.4f angle=%.2f clearance=%.4f' % (
        JointKey(JointID),
        float(Record['head_width_in']),
        float(Record['depth_in']),
        float(Record['flank_angle_deg']),
        float(Record['clearance_in'])
    )


def UpdateOperationUI(OperationValue):
    Operations = ['Create New', 'Edit Existing', 'Remove Existing']

    if isinstance(OperationValue, int):
        Operation = Operations[OperationValue]
    else:
        Operation = str(OperationValue)

    if Operation == 'Create New':
        ClearJointHighlight()
        for Key in _CapturedCreateSelections:
            _CapturedCreateSelections[Key] = None
        RestoreCreateCapturePrompts()
        ApplyDefaultsToInputs(USER_DEFAULTS)
        # Capture fields are display-only.  Keep them greyed out until the
        # selector captures geometry; the selector remains the input surface.
        Win.DisableInput(IDX_MALE)
        Win.DisableInput(IDX_FEMALE)
        Win.DisableInput(IDX_SEAM)
        Win.DisableInput(IDX_START)
        SetExistingJointControlForOperation(Operation)
        Win.DisableInput(IDX_MAXHEAD)

        for I in [
            IDX_LENGTHMODE, IDX_HEAD, IDX_DEPTH, IDX_ANGLE,
            IDX_CLEARANCE, IDX_DISTANCE, IDX_LIMITPLANE, IDX_MINWALL, IDX_BLEND
        ]:
            Win.EnableInput(I)

    elif Operation == 'Edit Existing':
        for Key in _CapturedCreateSelections:
            _CapturedCreateSelections[Key] = None
        Win.SetInputValue(IDX_MALE, None)
        Win.SetInputValue(IDX_FEMALE, None)
        Win.SetInputValue(IDX_SEAM, None)
        Win.SetInputValue(IDX_START, None)
        Win.DisableInput(IDX_MALE)
        Win.DisableInput(IDX_FEMALE)
        Win.DisableInput(IDX_SEAM)
        Win.DisableInput(IDX_START)
        SetExistingJointControlForOperation(Operation)
        Win.DisableInput(IDX_MAXHEAD)
        Win.DisableInput(IDX_MAXHEAD)

        for I in [
            IDX_LENGTHMODE, IDX_HEAD, IDX_DEPTH, IDX_ANGLE,
            IDX_CLEARANCE, IDX_DISTANCE, IDX_LIMITPLANE, IDX_MINWALL, IDX_BLEND
        ]:
            Win.EnableInput(I)

        LoadSelectedJointIntoUI(Win.GetInputValue(IDX_EXISTING))

    elif Operation == 'Remove Existing':
        for Key in _CapturedCreateSelections:
            _CapturedCreateSelections[Key] = None
        Win.SetInputValue(IDX_MALE, None)
        Win.SetInputValue(IDX_FEMALE, None)
        Win.SetInputValue(IDX_SEAM, None)
        Win.SetInputValue(IDX_START, None)
        Win.DisableInput(IDX_MALE)
        Win.DisableInput(IDX_FEMALE)
        Win.DisableInput(IDX_SEAM)
        Win.DisableInput(IDX_START)
        SetExistingJointControlForOperation(Operation)

        for I in [
            IDX_LENGTHMODE, IDX_HEAD, IDX_DEPTH, IDX_ANGLE,
            IDX_CLEARANCE, IDX_DISTANCE, IDX_LIMITPLANE, IDX_MINWALL, IDX_BLEND
        ]:
            Win.DisableInput(I)

        HighlightSelectedJoint(Win.GetInputValue(IDX_EXISTING))

    UpdateLengthModeInputs()
    UpdateMaxHeadDisplay()


def OnInputChanged(Index, Value):
    if Index == IDX_SAVEDEFAULTS:
        if Value not in (0, 'Choose defaults action...'):
            try:
                HandleDefaultsAction(Value)
            except Exception as Ex:
                Win.ErrorDialog('Could not update defaults. %s' % str(Ex), 'Sliding Dovetail Joint Manager')
            Win.SetInputValue(IDX_SAVEDEFAULTS, 0)

    elif Index == IDX_OPERATION:
        UpdateOperationUI(Value)

    elif Index == IDX_EXISTING:
        OperationValue = Win.GetInputValue(IDX_OPERATION)
        Operations = ['Create New', 'Edit Existing', 'Remove Existing']

        if isinstance(OperationValue, int):
            Operation = Operations[OperationValue]
        else:
            Operation = {'Create New Joint': 'Create New',
                         'Edit Existing Joint': 'Edit Existing',
                         'Remove Existing Joint': 'Remove Existing'}.get(str(OperationValue), str(OperationValue))

        if Operation == 'Edit Existing':
            LoadSelectedJointIntoUI(Value)
        elif Operation == 'Remove Existing':
            HighlightSelectedJoint(Value)
            UpdateMaxHeadDisplay()
        else:
            UpdateMaxHeadDisplay()

    elif Index == IDX_CAPTURE:
        return _StartSelectionCapture(Value)

    elif Index == IDX_LENGTHMODE:
        UpdateLengthModeInputs()

    elif Index in [
        IDX_START,
        IDX_ANGLE,
        IDX_CLEARANCE,
        IDX_MINWALL
    ]:
        UpdateMaxHeadDisplay()



# =============================================================================
# UI callback
# =============================================================================

def ManageJoint(V):
    global _HighlightBusy
    _HighlightBusy = True
    Succeeded = False
    ClearJointHighlight()
    try:
        OperationValue = V[IDX_OPERATION]
        ExistingJointValue = V[IDX_EXISTING]
        MalePart = _CapturedCreateSelections.get('male') or V[IDX_MALE]
        FemalePart = _CapturedCreateSelections.get('female') or V[IDX_FEMALE]
        SeamSelection = _CapturedCreateSelections.get('seam') or V[IDX_SEAM]
        StartSelection = _CapturedCreateSelections.get('start') or V[IDX_START]

        Operations = ['Create New', 'Edit Existing', 'Remove Existing']

        if isinstance(OperationValue, int):
            if OperationValue < 0 or OperationValue >= len(Operations):
                raise Exception('Invalid Operation selection.')
            Operation = Operations[OperationValue]
        else:
            Operation = str(OperationValue)

        ExistingJointNumber = None

        if Operation == 'Edit Existing' or Operation == 'Remove Existing':
            ExistingJointNumber = JointIDFromChoice(
                ExistingJointValue,
                ExistingJointChoices
            )

        # Remove Existing does not use the disabled capture/parameter fields.
        # Do not parse their instructional/blank values as floats.
        LengthMode = None
        LimitFaceSelection = None
        LimitPlaneName = None
        HeadWidth = Depth = AngleDeg = Clearance = DistanceLength = None
        MinWall = BlendRadius = None
        if Operation == 'Create New' or Operation == 'Edit Existing':
            LengthMode = NormalizeLengthMode(V[IDX_LENGTHMODE])
            LimitFaceSelection = _CapturedCreateSelections.get('limit') or V[IDX_LIMITPLANE]
            LimitPlaneName = CaptureLimitTarget(LimitFaceSelection) if (LengthMode == 'up_to_geometry' and Operation == 'Create New') else None
            HeadWidth = ToInternalLength(float(V[IDX_HEAD]))
            Depth = ToInternalLength(float(V[IDX_DEPTH]))
            AngleDeg = float(V[IDX_ANGLE])
            Clearance = ToInternalLength(float(V[IDX_CLEARANCE]))
            DistanceLength = ToInternalLength(float(V[IDX_DISTANCE]))
            MinWall = ToInternalLength(float(V[IDX_MINWALL]))
            BlendRadius = ToInternalLength(float(V[IDX_BLEND]))

        if Operation == 'Create New':
            Missing = []
            for Name, Selected in [('Male Part', _CapturedCreateSelections.get('male')), ('Female Part', _CapturedCreateSelections.get('female')), ('Shared Seam Edge', _CapturedCreateSelections.get('seam')), ('Shared Start Reference Edge', _CapturedCreateSelections.get('start'))]:
                if Selected is None:
                    Missing.append(Name)
            if Missing:
                raise Exception('Before Apply: select each required item in the workspace, then save each selection. Missing: %s.' % ', '.join(Missing))
            if LengthMode == 'up_to_geometry' and _CapturedCreateSelections.get('limit') is None:
                raise Exception('Before Apply: select the Limit Geometry Face and save that selection.')
            ValidateCommonInputs(
                MalePart, FemalePart,
                HeadWidth, Depth, AngleDeg,
                Clearance, DistanceLength, MinWall, BlendRadius
            )

            CreateNewJoint(
                MalePart, FemalePart,
                SeamSelection, StartSelection,
                LengthMode, HeadWidth, Depth, AngleDeg,
                Clearance, DistanceLength, LimitPlaneName,
                MinWall, BlendRadius
            )

            # Newly-created joint should immediately appear in the list.
            R = LoadRegistry()
            NewID = int(R.get('next_id', 1)) - 1
            RefreshExistingJointList(NewID)

            # Then return Create New to a clean/default state instead of
            # retaining the previous selections and dimensions.
            ResetCreateInputs()
            SetExistingJointControlForOperation('Create New')

        elif Operation == 'Edit Existing':
            if LengthMode == 'up_to_geometry' and LimitFaceSelection is not None and str(LimitFaceSelection).strip() != '':
                LimitPlaneName = CaptureLimitTarget(LimitFaceSelection)
            ValidateNumericInputs(
                HeadWidth, Depth, AngleDeg,
                Clearance, DistanceLength, MinWall, BlendRadius
            )

            EditStoredJoint(
                ExistingJointNumber,
                LengthMode, HeadWidth, Depth, AngleDeg,
                Clearance, DistanceLength, LimitPlaneName,
                MinWall, BlendRadius
            )

            # Joint identity/label does not change during an edit, so DO NOT
            # repopulate the StringList here. SetStringList resets selection to
            # the first item in Alibre. Keep the user's current joint selected.
            LoadSelectedJointIntoUI(ExistingJointValue)

        elif Operation == 'Remove Existing':
            RemoveStoredJoint(ExistingJointNumber)

            # Refresh the dropdown immediately so removed joints disappear
            # without closing/reopening the script.
            RefreshExistingJointList(None)
            ClearJointHighlight()

        Succeeded = True

    except Exception as Ex:
        print 'ERROR: %s' % str(Ex)
        Win.ErrorDialog(
            str(Ex),
            'Sliding Dovetail Joint Manager'
        )
    finally:
        _HighlightBusy = False
        try:
            Operation = CurrentOperation()
            if Operation == 'Edit Existing' or (Operation == 'Remove Existing' and not Succeeded):
                HighlightSelectedJoint(Win.GetInputValue(IDX_EXISTING))
        except Exception as Ex:
            print 'Joint highlight warning: refresh after Apply: %s' % str(Ex)

    return Succeeded


# =============================================================================
# Entry point
# =============================================================================

try:
    A = CurrentAssembly()
except:
    A = None

if A is None:
    sys.exit('Open an Assembly before running this script.')

Win = None

# Populate the existing-joint selector directly from the persistent registry.
# The user should never need to remember DT numbers.
try:
    _UIRegistry = LoadRegistry()
    ExistingJointChoices = BuildJointChoices(_UIRegistry)
except Exception as Ex:
    print 'Registry load warning: %s' % str(Ex)
    ExistingJointChoices = ['(No existing DT joints)']

# A blank pre-created custom property is still required; the POC proved
# SetCustomProperty writes an existing property but does not create it.
if ReadPropertyRaw() == '':
    print 'NOTE: %s is currently blank.' % PROPERTY_NAME
    print 'That is valid for a new registry, provided the custom property exists.'

# Populate assembly-level planes from the raw assembly DesignPlanes collection.
# This avoids the Alibre Script Plane-picker bug with assembly planes.

Options = []
Options.append(['Operation', WindowsInputTypes.StringList,
                ['Create New Joint', 'Edit Existing Joint', 'Remove Existing Joint'], 0])
Options.append(['Select geometry to capture', WindowsInputTypes.StringList, _CAPTURE_CHOICES, 0])
Options.append(['Existing Joint', WindowsInputTypes.StringList, ['(Not used for Create New Joint)'], 0])
Options.append(['Male Part', WindowsInputTypes.String, 'Select geometry in the workspace, then use the capture selector'])
Options.append(['Female Part', WindowsInputTypes.String, 'Select geometry in the workspace, then use the capture selector'])
Options.append(['Shared Seam Edge', WindowsInputTypes.String, 'Select geometry in the workspace, then use the capture selector'])
Options.append(['Shared Start Reference Edge', WindowsInputTypes.String, 'Select geometry in the workspace, then use the capture selector'])
LengthModeChoices = [
    'Full Seam',
    'Distance',
    'Up To Geometry'
]

Options.append([
    'Length Mode',
    WindowsInputTypes.StringList,
    LengthModeChoices,
    USER_DEFAULTS['length_mode']
])

Options.append(['Limit Geometry Face', WindowsInputTypes.String, 'Select geometry in the workspace, then use the capture selector'])
Options.append(['Male Head Width (%s)' % DISPLAY_UNIT, WindowsInputTypes.Real, ToDisplayLength(USER_DEFAULTS['head_width'])])
Options.append(['Dovetail Depth (%s)' % DISPLAY_UNIT, WindowsInputTypes.Real, ToDisplayLength(USER_DEFAULTS['depth'])])
Options.append(['Flank Angle (deg)', WindowsInputTypes.Real, USER_DEFAULTS['angle']])
Options.append(['Mating Surface Clearance (%s)' % DISPLAY_UNIT, WindowsInputTypes.Real, ToDisplayLength(USER_DEFAULTS['clearance'])])
Options.append(['Distance Length (%s)' % DISPLAY_UNIT, WindowsInputTypes.Real, ToDisplayLength(USER_DEFAULTS['distance'])])
Options.append(['Minimum Thickness Wall (%s)' % DISPLAY_UNIT, WindowsInputTypes.Real, ToDisplayLength(USER_DEFAULTS['min_wall'])])
Options.append(['Corner Blend Radius (%s)' % DISPLAY_UNIT, WindowsInputTypes.Real, ToDisplayLength(USER_DEFAULTS['blend_radius'])])
Options.append(['Max Male Head Width (%s)' % DISPLAY_UNIT, WindowsInputTypes.String, 'Select start edge'])
from dt_form import ManagerForm, run_manager

def CleanupManager():
    try:
        DisposeHighlightKeeper()
    finally:
        RestoreSessionUnits()

def CreateManagerForm():
    global Win
    Win = ManagerForm(Options, OnInputChanged, ManageJoint,
                      HandleDefaultsAction, CleanupManager,
                      'Sliding Dovetail Joint Manager v0.8.0', DISPLAY_UNIT, UnitChoices(), ChangeDisplayUnit)
    UpdateOperationUI(0)
    Win.RefreshOperation()
    return Win

run_manager(DT_Parent, CreateManagerForm)





