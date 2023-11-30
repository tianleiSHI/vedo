#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import numpy as np
from weakref import ref as weak_ref_to

import vedo.vtkclasses as vtk

import vedo
from vedo.transformations import LinearTransform
from vedo.visual import CommonVisual, Actor3DHelper, Actor2D

__docformat__ = "google"

__doc__ = """
Submodule for managing groups of vedo objects

![](https://vedo.embl.es/images/basic/align4.png)
"""

__all__ = ["Group", "Assembly", "procrustes_alignment"]


#################################################
def procrustes_alignment(sources, rigid=False):
    """
    Return an `Assembly` of aligned source meshes with the `Procrustes` algorithm.
    The output `Assembly` is normalized in size.

    The `Procrustes` algorithm takes N set of points and aligns them in a least-squares sense
    to their mutual mean. The algorithm is iterated until convergence,
    as the mean must be recomputed after each alignment.

    The set of average points generated by the algorithm can be accessed with
    `algoutput.info['mean']` as a numpy array.

    Arguments:
        rigid : bool
            if `True` scaling is disabled.

    Examples:
        - [align4.py](https://github.com/marcomusy/vedo/tree/master/examples/basic/align4.py)

        ![](https://vedo.embl.es/images/basic/align4.png)
    """

    group = vtk.new("MultiBlockDataGroupFilter")
    for source in sources:
        if sources[0].npoints != source.npoints:
            vedo.logger.error("sources have different nr of points")
            raise RuntimeError()
        group.AddInputData(source.dataset)
    procrustes = vtk.new("ProcrustesAlignmentFilter")
    procrustes.StartFromCentroidOn()
    procrustes.SetInputConnection(group.GetOutputPort())
    if rigid:
        procrustes.GetLandmarkTransform().SetModeToRigidBody()
    procrustes.Update()

    acts = []
    for i, s in enumerate(sources):
        poly = procrustes.GetOutput().GetBlock(i)
        mesh = vedo.mesh.Mesh(poly)
        mesh.actor.SetProperty(s.actor.GetProperty())
        mesh.properties = s.actor.GetProperty()
        if hasattr(s, "name"):
            mesh.name = s.name
        acts.append(mesh)
    assem = Assembly(acts)
    assem.transform = procrustes.GetLandmarkTransform()
    assem.info["mean"] = vedo.utils.vtk2numpy(procrustes.GetMeanPoints().GetData())
    return assem


#################################################
class Group(CommonVisual, vtk.vtkPropAssembly):
    """Form groups of generic objects (not necessarily meshes)."""

    def __init__(self, objects=()):
        """Form groups of generic objects (not necessarily meshes)."""

        super().__init__()

        self.actor = self

        self.name = "Group"
        self.filename = ""
        self.trail = None
        self.trail_points = []
        self.trail_segment_size = 0
        self.trail_offset = None
        self.shadows = []
        self.info = {}
        self.rendered_at = set()
        self.scalarbar = None

        for a in vedo.utils.flatten(objects):
            if a:
                self.AddPart(a.actor)

        self.PickableOff()


    def __iadd__(self, obj):
        """
        Add an object to the group
        """
        if not vedo.utils.is_sequence(obj):
            obj = [obj]
        for a in obj:
            if a:
                self.AddPart(a)
        return self

    def unpack(self):
        """Unpack the group into its elements"""
        elements = []
        self.InitPathTraversal()
        parts = self.GetParts()
        parts.InitTraversal()
        for i in range(parts.GetNumberOfItems()):
            ele = parts.GetItemAsObject(i)
            elements.append(ele)

        # gr.InitPathTraversal()
        # for _ in range(gr.GetNumberOfPaths()):
        #     path  = gr.GetNextPath()
        #     print([path])
        #     path.InitTraversal()
        #     for i in range(path.GetNumberOfItems()):
        #         a = path.GetItemAsObject(i).GetViewProp()
        #         print([a])

        return elements

    def clear(self):
        """Remove all parts"""
        for a in self.unpack():
            self.RemovePart(a)
        return self

    def on(self):
        """Switch on visibility"""
        self.VisibilityOn()
        return self

    def off(self):
        """Switch off visibility"""
        self.VisibilityOff()
        return self

    def pickable(self, value=None):
        """Set/get the pickability property of an object."""
        if value is None:
            return self.GetPickable()
        self.SetPickable(value)
        return self

    def draggable(self, value=None):
        """Set/get the draggability property of an object."""
        if value is None:
            return self.GetDragable()
        self.SetDragable(value)
        return self

    def pos(self, x=None, y=None):
        """Set/Get object 2D position on the screen."""
        if x is None:  # get functionality
            return np.array(self.GetPosition())

        if y is None:  # assume x is of the form (x,y)
            x, y = x
        self.SetPosition(x, y)
        return self

    def shift(self, ds):
        """Add a shift to the current object position on the screen."""
        p = np.array(self.GetPosition())
        self.SetPosition(p + ds)
        return self

    def bounds(self):
        """
        Get the object 2D bounds.
        Returns a list in format [xmin,xmax, ymin,ymax].
        """
        return self.GetBounds()


#################################################
class Assembly(CommonVisual, Actor3DHelper, vtk.vtkAssembly):
    """
    Group many objects and treat them as a single new object.
    """

    def __init__(self, *meshs):
        """
        Group many objects and treat them as a single new object,
        keeping track of internal transformations.

        Examples:
            - [gyroscope1.py](https://github.com/marcomusy/vedo/tree/master/examples/simulations/gyroscope1.py)

            ![](https://vedo.embl.es/images/simulations/39766016-85c1c1d6-52e3-11e8-8575-d167b7ce5217.gif)
        """
        super().__init__()

        # Init by filename
        if len(meshs) == 1 and isinstance(meshs[0], str):
            filename = vedo.file_io.download(meshs[0], verbose=False)
            data = np.load(filename, allow_pickle=True)
            meshs = [vedo.file_io._from_numpy(dd) for dd in data]

        if len(meshs) == 1:
            meshs = meshs[0]
        else:
            meshs = vedo.utils.flatten(meshs)

        self.actor = self
        self.actor.retrieve_object = weak_ref_to(self)

        self.name = "Assembly"
        self.filename = ""
        self.rendered_at = set()
        self.scalarbar = None
        self.info = {}
        self.time = 0

        self.transform = LinearTransform()

        self.objects = [m for m in meshs if m]
        self.actors  = [m.actor for m in self.objects]

        scalarbars = []
        for a in self.actors:
            if isinstance(a, vtk.get_class("Prop3D")): # and a.GetNumberOfPoints():
                self.AddPart(a)
            if hasattr(a, "scalarbar") and a.scalarbar is not None:
                scalarbars.append(a.scalarbar)

        if len(scalarbars) > 1:
            self.scalarbar = Group(scalarbars)
        elif len(scalarbars) == 1:
            self.scalarbar = scalarbars[0]

        self.pipeline = vedo.utils.OperationNode(
            "Assembly",
            parents=self.objects,
            comment=f"#meshes {len(self.objects)}",
            c="#f08080",
        )
        ##########################################

    def __str__(self):
        """Print info about Assembly object."""
        module = self.__class__.__module__
        name = self.__class__.__name__
        out = vedo.printc(
            f"{module}.{name} at ({hex(id(self))})".ljust(75),
            bold=True, invert=True, return_string=True,
        )
        out += "\x1b[0m"

        if self.name:
            out += "name".ljust(14) + ": " + self.name
            if "legend" in self.info.keys() and self.info["legend"]:
                out+= f", legend='{self.info['legend']}'"
            out += "\n"

        n = len(self.unpack())
        out += "n. of objects".ljust(14) + ": " + str(n) + " "
        names = [a.name for a in self.unpack() if a.name]
        if names:
            out += str(names).replace("'","")[:56]
        out += "\n"

        pos = self.GetPosition()
        out += "position".ljust(14) + ": " + str(pos) + "\n"

        bnds = self.GetBounds()
        bx1, bx2 = vedo.utils.precision(bnds[0], 3), vedo.utils.precision(bnds[1], 3)
        by1, by2 = vedo.utils.precision(bnds[2], 3), vedo.utils.precision(bnds[3], 3)
        bz1, bz2 = vedo.utils.precision(bnds[4], 3), vedo.utils.precision(bnds[5], 3)
        out+= "bounds".ljust(14) + ":"
        out+= " x=(" + bx1 + ", " + bx2 + "),"
        out+= " y=(" + by1 + ", " + by2 + "),"
        out+= " z=(" + bz1 + ", " + bz2 + ")\n"
        return out.rstrip() + "\x1b[0m"

    def _repr_html_(self):
        """
        HTML representation of the Assembly object for Jupyter Notebooks.

        Returns:
            HTML text with the image and some properties.
        """
        import io
        import base64
        from PIL import Image

        library_name = "vedo.assembly.Assembly"
        help_url = "https://vedo.embl.es/docs/vedo/assembly.html"

        arr = self.thumbnail(zoom=1.1, elevation=-60)

        im = Image.fromarray(arr)
        buffered = io.BytesIO()
        im.save(buffered, format="PNG", quality=100)
        encoded = base64.b64encode(buffered.getvalue()).decode("utf-8")
        url = "data:image/png;base64," + encoded
        image = f"<img src='{url}'></img>"

        # statisitics
        bounds = "<br/>".join(
            [
                vedo.utils.precision(min_x, 4) + " ... " + vedo.utils.precision(max_x, 4)
                for min_x, max_x in zip(self.bounds()[::2], self.bounds()[1::2])
            ]
        )

        help_text = ""
        if self.name:
            help_text += f"<b> {self.name}: &nbsp&nbsp</b>"
        help_text += '<b><a href="' + help_url + '" target="_blank">' + library_name + "</a></b>"
        if self.filename:
            dots = ""
            if len(self.filename) > 30:
                dots = "..."
            help_text += f"<br/><code><i>({dots}{self.filename[-30:]})</i></code>"

        allt = [
            "<table>",
            "<tr>",
            "<td>",
            image,
            "</td>",
            "<td style='text-align: center; vertical-align: center;'><br/>",
            help_text,
            "<table>",
            "<tr><td><b> nr. of objects </b></td><td>"
            + str(self.GetNumberOfPaths())
            + "</td></tr>",
            "<tr><td><b> position </b></td><td>" + str(self.GetPosition()) + "</td></tr>",
            "<tr><td><b> diagonal size </b></td><td>"
            + vedo.utils.precision(self.diagonal_size(), 5)
            + "</td></tr>",
            "<tr><td><b> bounds </b> <br/> (x/y/z) </td><td>" + str(bounds) + "</td></tr>",
            "</table>",
            "</table>",
        ]
        return "\n".join(allt)

    def __add__(self, obj):
        """
        Add an object to the assembly
        """
        if isinstance(obj, vtk.get_class("Prop3D")):

            self.objects.append(obj)
            self.actors.append(obj.actor)
            self.AddPart(obj.actor)

            if hasattr(obj, "scalarbar") and obj.scalarbar is not None:
                if self.scalarbar is None:
                    self.scalarbar = obj.scalarbar
                    return self

                def unpack_group(scalarbar):
                    if isinstance(scalarbar, Group):
                        return scalarbar.unpack()
                    else:
                        return scalarbar

                if isinstance(self.scalarbar, Group):
                    self.scalarbar += unpack_group(obj.scalarbar)
                else:
                    self.scalarbar = Group([unpack_group(self.scalarbar), unpack_group(obj.scalarbar)])
            self.pipeline = vedo.utils.OperationNode("add mesh", parents=[self, obj], c="#f08080")
        return self

    def __contains__(self, obj):
        """Allows to use `in` to check if an object is in the `Assembly`."""
        return obj in self.objects

    def __getitem__(self, i):
        """Return i-th object."""
        if isinstance(i, int):
            return self.objects[i]
        elif isinstance(i, str):
            for m in self.objects:
                if i in m.name:
                    return m
        return None

    def __len__(self):
        """Return nr. of objects in the assembly."""
        return len(self.objects)

    # TODO ####
    # def propagate_transform(self):
    #     """Propagate the transformation to all parts."""
    #     # navigate the assembly and apply the transform to all parts
    #     # and reset position, orientation and scale of the assembly
    #     for i in range(self.GetNumberOfPaths()):
    #         path = self.GetPath(i)
    #         obj = path.GetLastNode().GetViewProp()
    #         obj.SetUserTransform(self.transform.T)
    #         obj.SetPosition(0, 0, 0)
    #         obj.SetOrientation(0, 0, 0)
    #         obj.SetScale(1, 1, 1)
    #     raise NotImplementedError()

    def unpack(self, i=None):
        """Unpack the list of objects from a `Assembly`.

        If `i` is given, get `i-th` object from a `Assembly`.
        Input can be a string, in this case returns the first object
        whose name contains the given string.

        Examples:
            - [custom_axes4.py](https://github.com/marcomusy/vedo/tree/master/examples/pyplot/custom_axes4.py)
        """
        if i is None:
            return self.objects
        elif isinstance(i, int):
            return self.objects[i]
        elif isinstance(i, str):
            for m in self.objects:
                if i in m.name:
                    return m

    def recursive_unpack(self):
        """Flatten out an Assembly."""

        def _genflatten(lst):
            if not lst:
                return []
            ##
            if isinstance(lst[0], Assembly):
                lst = lst[0].unpack()
            ##
            for elem in lst:
                if isinstance(elem, Assembly):
                    apos = elem.GetPosition()
                    asum = np.sum(apos)
                    for x in elem.unpack():
                        if asum:
                            yield x.clone().shift(apos)
                        else:
                            yield x
                else:
                    yield elem

        return list(_genflatten([self]))

    def pickable(self, value=True):
        """Set/get the pickability property of an assembly and its elements"""
        self.SetPickable(value)
        # set property to each element
        for elem in self.recursive_unpack():
            elem.pickable(value)
        return self

    def clone(self):
        """Make a clone copy of the object. Same as `copy()`."""
        newlist = []
        for a in self.objects:
            newlist.append(a.clone())
        return Assembly(newlist)

    def clone2d(self, pos="bottom-left", scale=1, ontop=False):
        """
        Convert the `Assembly` into a `Group` of 2D objects.

        Arguments:
            pos : (list, str)
                Position in 2D, as a string or list (x,y).
                The center of the renderer is [0,0] while top-right is [1,1].
                Any combination of "center", "top", "bottom", "left" and "right" will work.
            scale : (float)
                global scaling factor for the 2D object.
                The scaling is normalized to the x-range of the original object.
            ontop : (bool)
                if `True` the now 2D object is rendered on top of the 3D scene.

        Returns:
            `Group` object.
        """
        padding = 0.05
        x0, x1 = self.xbounds()
        y0, y1 = self.ybounds()
        pp = self.pos()
        x0 -= pp[0]
        x1 -= pp[0]
        y0 -= pp[1]
        y1 -= pp[1]

        offset = [x0, y0]
        if "cent" in pos:
            offset = [(x0 + x1) / 2, (y0 + y1) / 2]
            position = [0, 0]
            if "right" in pos:
                offset[0] = x1
                position = [1 - padding, 0]
            if "left" in pos:
                offset[0] = x0
                position = [-1 + padding, 0]
            if "top" in pos:
                offset[1] = y1
                position = [0, 1 - padding]
            if "bottom" in pos:
                offset[1] = y0
                position = [0, -1 + padding]
        elif "top" in pos:
            if "right" in pos:
                offset = [x1, y1]
                position = [1 - padding, 1 - padding]
            elif "left" in pos:
                offset = [x0, y1]
                position = [-1 + padding, 1 - padding]
            else:
                raise ValueError(f"incomplete position pos='{pos}'")
        elif "bottom" in pos:
            if "right" in pos:
                offset = [x1, y0]
                position = [1 - padding, -1 + padding]
            elif "left" in pos:
                offset = [x0, y0]
                position = [-1 + padding, -1 + padding]
            else:
                raise ValueError(f"incomplete position pos='{pos}'")
        else:
            position = pos

        scanned = []
        group = Group()
        for a in self.recursive_unpack():
            if a in scanned:
                continue
            if not isinstance(a, vedo.Points):
                continue
            if a.npoints == 0:
                continue

            s = scale * 500 / (x1 - x0)
            if a.properties.GetRepresentation() == 1:
                # wireframe is not rendered correctly in 2d
                b = a.boundaries().lw(1).c(a.color(), a.alpha())
                a2d = b.clone2d(scale=s, offset=offset)
            else:
                a2d = a.clone2d(scale=s, offset=offset)
            a2d.pos(position).ontop(ontop)
            group += a2d

        try: # copy info from Histogram1D
            group.entries = self.entries
            group.frequencies = self.frequencies
            group.errors = self.errors
            group.edges = self.edges
            group.centers = self.centers
            group.mean = self.mean
            group.mode = self.mode
            group.std = self.std
        except AttributeError:
            pass

        group.name = self.name
        return group

    def copy(self):
        """Return a copy of the object. Alias of `clone()`."""
        return self.clone()

    def write(self, filename="assembly.npy"):
        """
        Write the object to file in `numpy` format.
        """
        objs = []
        for ob in self.unpack():
            d = vedo.file_io._to_numpy(ob)
            objs.append(d)
        np.save(filename, objs)
        return self
