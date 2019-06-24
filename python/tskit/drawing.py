# MIT License
#
# Copyright (c) 2018-2019 Tskit Developers
# Copyright (c) 2015-2017 University of Oxford
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
"""
Module responsible for visualisations.
"""
import collections
from _tskit import NULL

import svgwrite
import numpy as np

# NOTE: The code on the top of this module is marked for removal, to be replaced
# by the new SVG and Unicode tree drawing methods on the bottom. The aim is to
# make the current tree.draw() method use these functions, giving a simple high
# level interface. The draw_svg method on the other hand then gives a much
# more flexible way of drawing trees, with direct access to the SVG drawing
# primitives.


def check_format(format):
    if format is None:
        format = "SVG"
    fmt = format.lower()
    supported_formats = ["svg", "ascii", "unicode"]
    if fmt not in supported_formats:
        raise ValueError("Unknown format '{}'. Supported formats are {}".format(
            format, supported_formats))
    return fmt


def draw_tree(
        tree, width=None, height=None, node_labels=None, node_colours=None,
        mutation_labels=None, mutation_colours=None, format=None, edge_colours=None,
        tree_height_scale=None, max_tree_height=None):

    # See tree.draw() for documentation on these arguments.
    fmt = check_format(format)
    if fmt == "svg":
        if width is None:
            width = 200
        if height is None:
            height = 200
        td = SvgTreeDrawer(
            tree, width=width, height=height,
            node_labels=node_labels, node_colours=node_colours,
            mutation_labels=mutation_labels, mutation_colours=mutation_colours,
            edge_colours=edge_colours, tree_height_scale=tree_height_scale,
            max_tree_height=max_tree_height)
        return td.draw()
    else:
        if width is not None:
            raise ValueError("Text trees do not support width")
        if height is not None:
            raise ValueError("Text trees do not support height")
        if mutation_labels is not None:
            raise ValueError("Text trees do not support mutation_labels")
        if mutation_colours is not None:
            raise ValueError("Text trees do not support mutation_colours")
        if node_colours is not None:
            raise ValueError("Text trees do not support node_colours")
        if edge_colours is not None:
            raise ValueError("Text trees do not support edge_colours")
        if max_tree_height is not None:
            raise ValueError("Text trees do not support max_tree_height")

        use_ascii = fmt == "ascii"
        text_tree = RootTopTextTree(
            tree, node_labels=node_labels, max_tree_height=max_tree_height,
            use_ascii=use_ascii)
        return str(text_tree)


# NOTE The design of these classes is pretty poor. Could badly do with a rewrite.

class TreeDrawer(object):
    """
    A class to draw sparse trees in SVG format.
    """
    # NOTE: This was introduced as a way to centralise the SVG and text drawing
    # code, but isn't actually used now. Probably the right thing to do is to
    # have a more abstract 'canvas' idea which the backends draw onto, and the
    # coordinates get transformed as required.
    discretise_coordinates = False

    def _discretise(self, x):
        """
        Discetises the specified value, if necessary.
        """
        ret = x
        if self.discretise_coordinates:
            ret = int(round(x))
        return ret

    def __init__(
            self, tree, width=None, height=None, node_labels=None, node_colours=None,
            mutation_labels=None, mutation_colours=None, edge_colours=None,
            tree_height_scale=None, max_tree_height=None):
        self._tree = tree
        self._num_leaves = len(list(tree.leaves()))
        self._width = width
        self._height = height
        self._x_coords = {}
        self._y_coords = {}
        self._node_labels = {}
        self._node_colours = {}
        self._mutation_labels = {}
        self._mutation_colours = {}
        self._edge_colours = {}
        self._tree_height_scale = tree_height_scale
        self._max_tree_height = max_tree_height

        if tree_height_scale not in [None, "time", "rank"]:
            raise ValueError("tree_height_scale must be one of 'time' or 'rank'")
        numeric_max_tree_height = max_tree_height not in [None, "tree", "ts"]
        if tree_height_scale == "rank" and numeric_max_tree_height:
            raise ValueError("Cannot specify numeric max_tree_height with rank scale")

        # Set the node labels and colours.
        for u in tree.nodes():
            if node_labels is None:
                self._node_labels[u] = str(u)
            else:
                self._node_labels[u] = None
        if node_labels is not None:
            for node, label in node_labels.items():
                self._node_labels[node] = label
        if node_colours is not None:
            for node, colour in node_colours.items():
                self._node_colours[node] = colour
        if edge_colours is not None:
            for node, colour in edge_colours.items():
                self._edge_colours[node] = colour

        # Set the mutation labels.
        for site in tree.sites():
            for mutation in site.mutations:
                if mutation_labels is None:
                    self._mutation_labels[mutation.id] = str(mutation.id)
                else:
                    self._mutation_labels[mutation.id] = None
        if mutation_labels is not None:
            for mutation, label in mutation_labels.items():
                self._mutation_labels[mutation] = label
        if mutation_colours is not None:
            for mutation, colour in mutation_colours.items():
                self._mutation_colours[mutation] = colour

        self._assign_y_coordinates()
        self._assign_x_coordinates()


class SvgTreeDrawer(TreeDrawer):
    """
    Draws trees in SVG format using the svgwrite library.
    """
    def _assign_y_coordinates(self):
        tree = self._tree
        ts = tree.tree_sequence
        if self._tree_height_scale in [None, "time"]:
            if self._max_tree_height in [None, "tree"]:
                max_tree_height = max(tree.time(root) for root in tree.roots)
            elif self._max_tree_height == "ts":
                max_tree_height = ts.max_root_time
            else:
                # Use the numeric tree height value directly.
                max_tree_height = self._max_tree_height
            node_height = {u: tree.time(u) for u in tree.nodes()}
        else:
            assert self._tree_height_scale == "rank"
            assert self._max_tree_height in [None, "tree", "ts"]
            if self._max_tree_height in [None, "tree"]:
                times = {tree.time(u) for u in tree.nodes()}
            elif self._max_tree_height == "ts":
                times = {node.time for node in ts.nodes()}
            depth = {t: 2 * j for j, t in enumerate(sorted(times))}
            node_height = {u: depth[tree.time(u)] for u in tree.nodes()}
            max_tree_height = max(depth.values())
        # In pathological cases, all the roots are at 0
        if max_tree_height == 0:
            max_tree_height = 1

        y_padding = 20
        mutations_over_root = any(
            tree.parent(mut.node) == NULL for mut in tree.mutations())
        root_branch_length = 0
        if mutations_over_root:
            # Allocate a fixed about of space to show the mutations on the
            # 'root branch'
            root_branch_length = self._height / 10
        self._y_scale = (
            self._height - root_branch_length - 2 * y_padding) / max_tree_height
        self._y_coords[-1] = y_padding
        for u in tree.nodes():
            scaled_h = node_height[u] * self._y_scale
            self._y_coords[u] = self._height - scaled_h - y_padding

    def _assign_x_coordinates(self):
        self._x_scale = self._width / (self._num_leaves + 2)
        self._leaf_x = 1
        for root in self._tree.roots:
            self._assign_x_coordinates_node(root)
        self._mutations = []
        node_mutations = collections.defaultdict(list)
        for site in self._tree.sites():
            for mutation in site.mutations:
                node_mutations[mutation.node].append(mutation)
        for child, mutations in node_mutations.items():
            n = len(mutations)
            parent = self._tree.parent(child)
            # Ignore any mutations that are above non-roots that are
            # not in the current tree.
            if child in self._x_coords:
                x = self._x_coords[child]
                y1 = self._y_coords[child]
                y2 = self._y_coords[parent]
                chunk = (y2 - y1) / (n + 1)
                for k, mutation in enumerate(mutations):
                    z = x, self._discretise(y1 + (k + 1) * chunk)
                    self._mutations.append((z, mutation))

    def _assign_x_coordinates_node(self, node):
        """
        Assign x coordinates to all nodes underneath this node.
        """
        if self._tree.is_internal(node):
            children = self._tree.children(node)
            for c in children:
                self._assign_x_coordinates_node(c)
            coords = [self._x_coords[c] for c in children]
            a = min(coords)
            b = max(coords)
            self._x_coords[node] = self._discretise(a + (b - a) / 2)
        else:
            self._x_coords[node] = self._discretise(self._leaf_x * self._x_scale)
            self._leaf_x += 1

    def draw(self):
        """
        Writes the SVG description of this tree and returns the resulting XML
        code as text.
        """
        dwg = svgwrite.Drawing(size=(self._width, self._height), debug=True)
        default_edge_colour = "black"
        default_node_colour = "black"
        default_mutation_colour = "red"
        lines = dwg.add(dwg.g(id='lines', stroke=default_edge_colour))
        nodes = dwg.add(dwg.g(id='nodes', fill=default_node_colour))
        mutations = dwg.add(dwg.g(id='mutations', fill=default_mutation_colour))
        left_labels = dwg.add(dwg.g(font_size=14, text_anchor="start"))
        right_labels = dwg.add(dwg.g(font_size=14, text_anchor="end"))
        mid_labels = dwg.add(dwg.g(font_size=14, text_anchor="middle"))
        for u in self._tree.nodes():
            v = self._tree.get_parent(u)
            x = self._x_coords[u], self._y_coords[u]
            fill = self._node_colours.get(u, default_node_colour)
            if fill is not None:
                # Keep SVG small and clean by only adding node markers if required,
                # and only specifying a fill colour if not the default
                params = {} if fill == default_node_colour else {'fill': fill}
                nodes.add(dwg.circle(center=x, r=3, **params))
            dx = 0
            dy = -5
            labels = mid_labels
            if self._tree.is_leaf(u):
                dy = 20
            elif self._tree.parent(u) != NULL:
                dx = 5
                if self._tree.left_sib(u) == NULL:
                    dx *= -1
                    labels = right_labels
                else:
                    labels = left_labels
            if self._node_labels[u] is not None:
                labels.add(dwg.text(self._node_labels[u], (x[0] + dx, x[1] + dy)))
            if self._tree.parent(u) != NULL:
                y = self._x_coords[v], self._y_coords[v]
                stroke = self._edge_colours.get(u, default_edge_colour)
                if stroke is not None:
                    # Keep SVG small and clean
                    params = {} if stroke == default_edge_colour else {'stroke': stroke}
                    lines.add(dwg.line(x, (x[0], y[1]), **params))
                    lines.add(dwg.line((x[0], y[1]), y, **params))

        # Experimental stuff to render the mutation labels. Not working very
        # well at the moment.
        left_labels = dwg.add(dwg.g(
            font_size=14, text_anchor="start", font_style="italic",
            alignment_baseline="middle"))
        right_labels = dwg.add(dwg.g(
            font_size=14, text_anchor="end", font_style="italic",
            alignment_baseline="middle"))
        for x, mutation in self._mutations:
            r = 3
            fill = self._mutation_colours.get(mutation.id, default_mutation_colour)
            if fill is not None:
                # Keep SVG small and clean
                params = {} if fill == default_mutation_colour else {'fill': fill}
                mutations.add(dwg.rect(
                    insert=(x[0] - r, x[1] - r), size=(2 * r, 2 * r), **params))
            dx = 5
            if self._tree.left_sib(mutation.node) == NULL:
                dx *= -1
                labels = right_labels
            else:
                labels = left_labels
            if self._mutation_labels[mutation.id] is not None:
                dy = 1.5 * r
                labels.add(dwg.text(
                    self._mutation_labels[mutation.id], (x[0] + dx, x[1] + dy)))
        return dwg.tostring()
        # return dwg


#
# New API - separate classes for drawing text and SVG
#

class SvgTreeSequence(object):
    """
    TODO: this is badly structured right now. What we should do is
    Move all of the tree drawing logic into the SvgTree class, and then
    this class should combine these linearly. Each tree will be an
    independant SVG entity, so that we can manipulate it.
    """

    def __init__(
            self, ts, size=None, tree_height_scale=None, max_tree_height=None,
            node_attrs=None, edge_attrs=None, node_label_attrs=None):
        self.ts = ts
        if size is None:
            size = (200 * ts.num_trees, 200)
        self.image_size = size
        self.drawing = svgwrite.Drawing(size=self.image_size, debug=True)
        self.node_labels = {u: str(u) for u in range(ts.num_nodes)}
        # TODO add general padding arguments following matplotlib's terminology.
        self.axes_x_offset = 15
        self.axes_y_offset = 10
        self.treebox_x_offset = self.axes_x_offset + 5
        self.treebox_y_offset = self.axes_y_offset + 5
        x = self.treebox_x_offset
        treebox_width = size[0] - 2 * self.treebox_x_offset
        treebox_height = size[1] - 2 * self.treebox_y_offset
        tree_width = treebox_width / ts.num_trees
        svg_trees = [
            SvgTree(
                tree, (tree_width, treebox_height),
                tree_height_scale=tree_height_scale,
                node_attrs=node_attrs, edge_attrs=edge_attrs,
                node_label_attrs=node_label_attrs)
            for tree in ts.trees()]

        ticks = []
        y = self.treebox_y_offset
        defs = self.drawing.defs

        for tree, svg_tree in zip(ts.trees(), svg_trees):
            defs.add(svg_tree.root_group)

        for tree in ts.trees():
            tree_id = "#tree_{}".format(tree.index)
            use = self.drawing.use(tree_id, (x, y))
            self.drawing.add(use)
            ticks.append((x, tree.interval[0]))
            x += tree_width
        ticks.append((x, ts.sequence_length))

        dwg = self.drawing

        # # Debug --- draw the tree and axes boxes
        # w = self.image_size[0] - 2 * self.treebox_x_offset
        # h = self.image_size[1] - 2 * self.treebox_y_offset
        # dwg.add(dwg.rect((self.treebox_x_offset, self.treebox_y_offset), (w, h),
        #     fill="white", fill_opacity=0, stroke="black", stroke_dasharray="15,15"))
        # w = self.image_size[0] - 2 * self.axes_x_offset
        # h = self.image_size[1] - 2 * self.axes_y_offset
        # dwg.add(dwg.rect((self.axes_x_offset, self.axes_y_offset), (w, h),
        #     fill="white", fill_opacity=0, stroke="black", stroke_dasharray="5,5"))

        axes_left = self.treebox_x_offset
        axes_right = self.image_size[0] - self.treebox_x_offset
        y = self.image_size[1] - 2 * self.axes_y_offset
        dwg.add(dwg.line((axes_left, y), (axes_right, y), stroke="black"))
        for x, genome_coord in ticks:
            delta = 5
            dwg.add(dwg.line((x, y - delta), (x, y + delta), stroke="black"))
            dwg.add(dwg.text(
                "{:.2f}".format(genome_coord), (x, y + 20),
                font_size=14, text_anchor="middle", font_weight="bold"))


class SvgTree(object):
    """
    An SVG representation of a single tree.

    TODO should provide much more SVG structure which we document fully
    to that the SVG elements can be manipulated directly by the user.
    For example, every edge should be given an SVG ID so that it can
    be referred to and modified.

    """
    def __init__(
            self, tree, size=None, tree_height_scale=None, max_tree_height=None,
            node_attrs=None, edge_attrs=None, node_label_attrs=None):
        self.tree = tree
        if size is None:
            size = (200, 200)
        self.image_size = size
        self.setup_drawing()
        self.node_labels = {u: str(u) for u in tree.nodes()}
        self.treebox_x_offset = 10
        self.treebox_y_offset = 10
        self.treebox_width = size[0] - 2 * self.treebox_x_offset
        self.assign_y_coordinates(tree_height_scale, max_tree_height)
        self.node_x_coord_map = self.assign_x_coordinates(
            tree, self.treebox_x_offset, self.treebox_width)
        self.edge_attrs = {}
        self.node_attrs = {}
        self.node_label_attrs = {}
        for u in tree.nodes():
            self.edge_attrs[u] = {}
            if edge_attrs is not None and u in edge_attrs:
                self.edge_attrs[u].update(edge_attrs[u])
            self.node_attrs[u] = {"r": 3}
            if node_attrs is not None and u in node_attrs:
                self.node_attrs[u].update(node_attrs[u])
            self.node_label_attrs[u] = {"text": "{}".format(u)}
            if node_label_attrs is not None and u in node_label_attrs:
                self.node_label_attrs[u].update(node_label_attrs[u])
        self.draw()

    def setup_drawing(self):
        self.drawing = svgwrite.Drawing(size=self.image_size, debug=True)
        dwg = self.drawing
        self.root_group = dwg.add(dwg.g(id='tree_{}'.format(self.tree.index)))
        self.edges = self.root_group.add(dwg.g(id='edges',  stroke="black", fill="none"))
        self.symbols = self.root_group.add(dwg.g(id='symbols'))
        self.nodes = self.symbols.add(dwg.g(class_='nodes'))
        self.mutations = self.symbols.add(dwg.g(class_='mutations', fill="red"))
        self.labels = self.root_group.add(dwg.g(id='labels', font_size=14))
        self.node_labels = self.labels.add(dwg.g(class_='nodes'))
        self.mutation_labels = self.labels.add(
            dwg.g(class_='mutations', font_style="italic", alignment_baseline="middle"))
        self.left_labels = self.node_labels.add(dwg.g(text_anchor="start"))
        self.mid_labels = self.node_labels.add(dwg.g(text_anchor="middle"))
        self.right_labels = self.node_labels.add(dwg.g(text_anchor="end"))
        self.mutation_left_labels = self.mutation_labels.add(dwg.g(text_anchor="start"))
        self.mutation_right_labels = self.mutation_labels.add(dwg.g(text_anchor="end"))

    def assign_y_coordinates(self, tree_height_scale, max_tree_height):
        ts = self.tree.tree_sequence
        node_time = ts.tables.nodes.time
        if tree_height_scale in [None, "time"]:
            node_height = node_time
            if max_tree_height is None:
                max_tree_height = ts.max_root_time
        else:
            if tree_height_scale != "rank":
                raise ValueError(
                    "Only 'time' and 'rank' are supported for tree_height_scale")
            depth = {t: 2 * j for j, t in enumerate(np.unique(node_time))}
            node_height = [depth[node_time[u]] for u in range(ts.num_nodes)]
            if max_tree_height is None:
                max_tree_height = max(depth.values())
        # In pathological cases, all the roots are at 0
        if max_tree_height == 0:
            max_tree_height = 1

        # TODO should make this a parameter somewhere. This is padding to keep the
        # node labels within the treebox
        label_padding = 10
        y_padding = self.treebox_y_offset + 2 * label_padding
        mutations_over_root = any(
            any(tree.parent(mut.node) == NULL for mut in tree.mutations())
            for tree in ts.trees())
        root_branch_length = 0
        height = self.image_size[1]
        if mutations_over_root:
            # Allocate a fixed about of space to show the mutations on the
            # 'root branch'
            root_branch_length = height / 10  # FIXME just draw branch??
        y_scale = (height - root_branch_length - 2 * y_padding) / max_tree_height
        self.node_y_coord_map = [
                height - y_scale * node_height[u] - y_padding
                for u in range(ts.num_nodes)]

    def assign_x_coordinates(self, tree, x_start, width):
        num_leaves = len(list(tree.leaves()))
        x_scale = width / (num_leaves + 1)
        node_x_coord_map = {}
        leaf_x = x_start
        for root in tree.roots:
            for u in tree.nodes(root, order="postorder"):
                if tree.is_leaf(u):
                    leaf_x += x_scale
                    node_x_coord_map[u] = leaf_x
                else:
                    child_coords = [node_x_coord_map[c] for c in tree.children(u)]
                    if len(child_coords) == 1:
                        node_x_coord_map[u] = child_coords[0]
                    else:
                        a = min(child_coords)
                        b = max(child_coords)
                        assert b - a > 1
                        node_x_coord_map[u] = a + (b - a) / 2
        return node_x_coord_map

    def draw(self):
        dwg = self.drawing
        node_x_coord_map = self.node_x_coord_map
        node_y_coord_map = self.node_y_coord_map
        tree = self.tree

        node_mutations = collections.defaultdict(list)
        for site in tree.sites():
            for mutation in site.mutations:
                node_mutations[mutation.node].append(mutation)

        for u in tree.nodes():
            pu = node_x_coord_map[u], node_y_coord_map[u]
            node_id = "node_{}_{}".format(tree.index, u)
            self.nodes.add(dwg.circle(id=node_id, center=pu, **self.node_attrs[u]))
            dx = 0
            dy = -5
            labels = self.mid_labels
            if tree.is_leaf(u):
                dy = 20
            elif tree.parent(u) != NULL:
                dx = 5
                if tree.left_sib(u) == NULL:
                    dx *= -1
                    labels = self.right_labels
                else:
                    labels = self.left_labels
            # TODO add ID to node label text.
            labels.add(dwg.text(
                insert=(pu[0] + dx, pu[1] + dy), **self.node_label_attrs[u]))
            v = tree.parent(u)
            if v != NULL:
                edge_id = "edge_{}_{}".format(tree.index, u)
                pv = node_x_coord_map[v], node_y_coord_map[v]
                path = dwg.path(
                    [("M", pu), ("V", pv[1]), ("H", pv[0])], id=edge_id,
                    **self.edge_attrs[u])
                self.edges.add(path)

                # TODO do something with mutations over the root
                # Draw the mutations
                num_mutations = len(node_mutations[u])
                delta = (pv[1] - pu[1]) / (num_mutations + 1)
                x = pu[0]
                y = pv[1] - delta
                r = 3
                # TODO add support for manipulating mutation properties and IDs
                for mutation in node_mutations[u]:
                    self.mutations.add(dwg.rect(
                        insert=(x - r, y - r), size=(2 * r, 2 * r)))
                    dx = 5
                    if tree.left_sib(mutation.node) == NULL:
                        dx *= -1
                        labels = self.mutation_right_labels
                    else:
                        labels = self.mutation_left_labels
                    dy = 1.5 * r
                    labels.add(dwg.text(str(mutation.id), (x + dx, y + dy)))
                    y -= delta


class TextTreeSequence(object):
    """
    Draw a tree sequence as horizontal line of trees.
    """
    def __init__(
            self, ts, node_labels=None, use_ascii=False, time_label_format=None,
            position_label_format=None):
        self.ts = ts

        time_label_format = (
            "{:.2f}" if time_label_format is None else time_label_format)
        position_label_format = (
            "{:.2f}" if position_label_format is None else position_label_format)

        time = ts.tables.nodes.time
        time_scale_labels = [
            time_label_format.format(time[u]) for u in range(ts.num_nodes)]
        position_scale_labels = [
            position_label_format.format(x) for x in ts.breakpoints()]
        trees = [
            RootTopTextTree(
                tree, max_tree_height="ts", node_labels=node_labels,
                use_ascii=use_ascii)
            for tree in self.ts.trees()]

        self.height = 1 + max(tree.height for tree in trees)
        self.width = sum(tree.width + 2 for tree in trees) - 1
        max_time_scale_label_len = max(map(len, time_scale_labels))
        self.width += 3 + max_time_scale_label_len + len(position_scale_labels[-1]) // 2

        self.canvas = np.zeros((self.height, self.width), dtype=str)
        self.canvas[:] = " "

        vertical_sep = "|" if use_ascii else "┊"

        x = 0
        for u, label in enumerate(map(to_np_unicode, time_scale_labels)):
            y = trees[0].time_position[u]
            self.canvas[y, 0: label.shape[0]] = label
        self.canvas[:, max_time_scale_label_len] = vertical_sep
        x = 2 + max_time_scale_label_len

        for j, tree in enumerate(trees):
            pos_label = to_np_unicode(position_scale_labels[j])
            k = len(pos_label)
            label_x = max(x - k // 2 - 2, 0)
            self.canvas[-1, label_x: label_x + k] = pos_label
            h, w = tree.canvas.shape
            self.canvas[-h - 1: -1, x: x + w - 1] = tree.canvas[:, :-1]
            x += w
            self.canvas[:, x] = vertical_sep
            x += 2

        pos_label = to_np_unicode(position_scale_labels[-1])
        k = len(pos_label)
        label_x = max(x - k // 2 - 2, 0)
        self.canvas[-1, label_x: label_x + k] = pos_label
        self.canvas[:, -1] = "\n"

    def __str__(self):
        return "".join(self.canvas.reshape(self.width * self.height))


LEFT = "left"
RIGHT = "right"
TOP = "top"


def check_orientation(orientation):
    if orientation is None:
        orientation = TOP
    else:
        orientation = orientation.lower()
        orientations = [LEFT, RIGHT, TOP]
        if orientation not in orientations:
            raise ValueError(
                "Unknown orientiation: choose from {}".format(orientations))
    return orientation


def check_max_tree_height(max_tree_height):
    if max_tree_height is None:
        max_tree_height = "tree"
    if max_tree_height not in ["tree", "ts"]:
        raise ValueError("max_tree_height must be 'tree' or 'ts'")
    return max_tree_height


def to_np_unicode(string):
    """
    Converts the specified string to a numpy unicode array.
    """
    # TODO: what's the clean of doing this with numpy?
    # It really wants to create a zero-d Un array here
    # which breaks the assignment below and we end up
    # with n copies of the first char.
    n = len(string)
    np_string = np.zeros(n, dtype="U")
    for j in range(n):
        np_string[j] = string[j]
    return np_string


def closest_left_node(tree, u):
    """
    Returns the node that closest to u in a left-to-right sense.
    """
    ret = NULL
    while u != NULL and ret == NULL:
        ret = tree.left_sib(u)
        u = tree.parent(u)
    return ret


def node_time_depth(tree, min_branch_length=None):
    """
    Returns a dictionary mapping nodes in the specified tree to their depth
    in the specified tree (from the root direction). If min_branch_len is
    provided, it specifies the minimum length of each branch. If not specified,
    default to 1.
    """
    if min_branch_length is None:
        min_branch_length = {u: 1 for u in tree.nodes()}
    time_node_map = collections.defaultdict(list)
    for u in tree.nodes():
        time_node_map[tree.time(u)].append(u)
    current_depth = 0
    depth = {}
    for t in sorted(time_node_map.keys()):
        for u in time_node_map[t]:
            for v in tree.children(u):
                current_depth = max(current_depth, depth[v] + min_branch_length[v])
        for u in time_node_map[t]:
            depth[u] = current_depth
        current_depth += 2
    for root in tree.roots:
        current_depth = max(current_depth, depth[root] + min_branch_length[root])
    return depth, current_depth


class TextTree(object):
    """
    Draws a reprentation of a tree using unicode drawing characters written
    to a 2D array.
    """
    def __init__(
            self, tree, node_labels=None, max_tree_height=None, use_ascii=False,
            orientation=None):
        self.tree = tree
        self.max_tree_height = check_max_tree_height(max_tree_height)
        self.use_ascii = use_ascii
        self.orientation = orientation
        self.horizontal_line_char = '━'
        self.vertical_line_char = '┃'
        if use_ascii:
            self.horizontal_line_char = '-'
            self.vertical_line_char = '|'
        # These are set below by the placement algorithms.
        self.width = None
        self.height = None
        self.canvas = None
        # Placement of nodes in the 2D space. Nodes are positioned in one
        # dimension based on traversal ordering and by their time in the
        # other dimension. These are mapped to x and y coordinates according
        # to the orientation.
        self.traversal_position = {}  # Position of nodes in traversal space
        self.time_position = {}
        # Labels for nodes
        self.node_labels = {}

        # Set the node labels
        for u in tree.nodes():
            if node_labels is None:
                # If we don't specify node_labels, default to node ID
                self.node_labels[u] = str(u)
            else:
                # If we do specify node_labels, default an empty line
                self.node_labels[u] = self.default_node_label
        if node_labels is not None:
            for node, label in node_labels.items():
                self.node_labels[node] = label

        self._assign_time_positions()
        self._assign_traversal_positions()
        self.canvas = np.zeros((self.height, self.width), dtype=str)
        self.canvas[:] = " "
        self._draw()
        self.canvas[:, -1] = "\n"

    def __str__(self):
        return "".join(self.canvas.reshape(self.width * self.height))


class RootTopTextTree(TextTree):
    """
    Text tree rendering where root nodes are at the top and time goes downwards
    into the present.
    """
    @property
    def default_node_label(self):
        return self.vertical_line_char

    def _assign_time_positions(self):
        tree = self.tree
        ts = tree.tree_sequence
        if self.max_tree_height == "tree":
            nodes = list(tree.nodes())
        else:
            assert self.max_tree_height == "ts"
            nodes = range(ts.num_nodes)
        times = {ts.node(u).time for u in nodes}
        depth = {t: 2 * j for j, t in enumerate(sorted(times, reverse=True))}
        for u in nodes:
            self.time_position[u] = depth[self.tree.time(u)]
        self.height = max(self.time_position.values()) + 1

    def _assign_traversal_positions(self):
        self.label_x = {}
        x = 0
        for root in self.tree.roots:
            for u in self.tree.nodes(root, order="postorder"):
                label_size = len(self.node_labels[u])
                if self.tree.is_leaf(u):
                    self.traversal_position[u] = x + label_size // 2
                    self.label_x[u] = x
                    x += label_size + 1
                else:
                    coords = [self.traversal_position[c] for c in self.tree.children(u)]
                    if len(coords) == 1:
                        self.traversal_position[u] = coords[0]
                    else:
                        a = min(coords)
                        b = max(coords)
                        child_mid = int(round((a + (b - a) / 2)))
                        self.traversal_position[u] = child_mid
                    self.label_x[u] = self.traversal_position[u] - label_size // 2
                    sib_x = -1
                    sib = closest_left_node(self.tree, u)
                    if sib != NULL:
                        sib_x = self.traversal_position[sib]
                    self.label_x[u] = max(sib_x + 1, self.label_x[u])
                    x = max(x, self.label_x[u] + label_size + 1)
                assert self.label_x[u] >= 0
            x += 1
        self.width = x - 1

    def _draw(self):
        # TODO follow the pattern used in the horizontal tree below and implement
        # orientation = down also.
        mid_up_char = "+" if self.use_ascii else "┻"
        mid_down_char = "+" if self.use_ascii else "┳"
        mid_up_down_char = "+" if self.use_ascii else "╋"
        left_down_char = "+" if self.use_ascii else "┏"
        right_down_char = "+" if self.use_ascii else "┓"

        for u in self.tree.nodes():
            xu = self.traversal_position[u]
            yu = self.time_position[u]
            label = to_np_unicode(self.node_labels[u])
            label_len = label.shape[0]
            label_x = self.label_x[u]
            assert label_x >= 0
            self.canvas[yu, label_x: label_x + label_len] = label
            children = self.tree.children(u)
            if len(children) > 0:
                if len(children) == 1:
                    yv = self.time_position[children[0]]
                    self.canvas[yu + 1: yv, xu] = self.vertical_line_char
                else:
                    left = min(self.traversal_position[v] for v in children)
                    right = max(self.traversal_position[v] for v in children)
                    y = yu + 1
                    self.canvas[y, left + 1: right] = self.horizontal_line_char
                    self.canvas[y, xu] = mid_up_char
                    for v in children:
                        xv = self.traversal_position[v]
                        yv = self.time_position[v]
                        self.canvas[yu + 2: yv, xv] = self.vertical_line_char
                        mid_char = mid_up_down_char if xv == xu else mid_down_char
                        self.canvas[yu + 1, xv] = mid_char
                    self.canvas[y, left] = left_down_char
                    self.canvas[y, right] = right_down_char
        # print(self.canvas)


class HorizontalTextTree(TextTree):
    """
    Text tree rendering where root nodes are at the left and time goes
    rightwards into the present.
    """

    @property
    def default_node_label(self):
        return self.horizontal_line_char

    def _assign_time_positions(self):
        tree = self.tree
        # ts = tree.tree_sequence
        # if self.max_tree_height == "tree":
        #     nodes = list(tree.nodes())
        # else:
        #     assert self.max_tree_height == "ts"
        #     nodes = range(ts.num_nodes)

        # FIXME this is ignoring the "ts" argument - make the max across all trees
        # or something?
        self.time_position, total_depth = node_time_depth(
            tree, {u: 1 + len(self.node_labels[u]) for u in tree.nodes()})
        self.width = total_depth

    def _assign_traversal_positions(self):
        y = 0
        for root in self.tree.roots:
            for u in self.tree.nodes(root, order="postorder"):
                if self.tree.is_leaf(u):
                    self.traversal_position[u] = y
                    y += 2
                else:
                    coords = [self.traversal_position[c] for c in self.tree.children(u)]
                    if len(coords) == 1:
                        self.traversal_position[u] = coords[0]
                    else:
                        a = min(coords)
                        b = max(coords)
                        child_mid = int(round((a + (b - a) / 2)))
                        self.traversal_position[u] = child_mid
            y += 1
        self.height = y - 2

    def _draw(self):
        if self.use_ascii:
            top_across = "+"
            bot_across = "+"
            mid_parent = "+"
            mid_parent_child = "+"
            mid_child = "+"
        elif self.orientation == LEFT:
            top_across = "┏"
            bot_across = "┗"
            mid_parent = "┫"
            mid_parent_child = "╋"
            mid_child = "┣"
        else:
            top_across = "┓"
            bot_across = "┛"
            mid_parent = "┣"
            mid_parent_child = "╋"
            mid_child = "┫"

        # Draw in root-right mode as the coordinates go in the expected direction.
        for u in self.tree.nodes():
            yu = self.traversal_position[u]
            xu = self.time_position[u]
            label = to_np_unicode(self.node_labels[u])
            if self.orientation == LEFT:
                # We flip the array at the end so need to reverse the label.
                label = label[::-1]
            label_len = label.shape[0]
            self.canvas[yu, xu: xu + label_len] = label
            children = self.tree.children(u)
            if len(children) > 0:
                if len(children) == 1:
                    yv = self.time_position[children[0]]
                    self.canvas[yu: yv + 1, xu] = self.horizontal_line_char
                else:
                    bot = min(self.traversal_position[v] for v in children)
                    top = max(self.traversal_position[v] for v in children)
                    x = xu - 1
                    self.canvas[bot + 1: top, x] = self.vertical_line_char
                    self.canvas[yu, x] = mid_parent
                    for v in children:
                        yv = self.traversal_position[v]
                        xv = self.time_position[v]
                        self.canvas[yv, xv: x] = self.horizontal_line_char
                        mid_char = mid_parent_child if yv == yu else mid_child
                        self.canvas[yv, x] = mid_char
                    self.canvas[bot, x] = top_across
                    self.canvas[top, x] = bot_across
        if self.orientation == LEFT:
            self.canvas = np.flip(self.canvas, axis=1)
            # Move the padding to the left.
            self.canvas[:, :-1] = self.canvas[:, 1:]
            self.canvas[:, -1] = " "
        # print(self.canvas)
