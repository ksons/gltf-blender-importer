import bpy
from mathutils import Vector, Quaternion, Matrix


class Curve:
    @staticmethod
    def for_sampler(op, sampler, num_targets=None):
        c = Curve()

        c.times = op.get('accessor', sampler['input'])
        c.ords = op.get('accessor', sampler['output'])
        c.interp = sampler.get('interpolation', 'LINEAR')
        if c.interp not in ['LINEAR', 'STEP', 'CUBICSPLINE']:
            print('unknown interpolation: %s', c.interp)
            c.interp = 'LINEAR'

        if num_targets != None:
            # Group one frame's worth of morph weights together.
            c.ords = [
                c.ords[i: i + num_targets]
                for i in range(0, len(c.ords), num_targets)
            ]

        if c.interp == 'CUBICSPLINE':
            # Move the in-tangents and out-tangents into separate arrays.
            c.ins, c.ords, c.outs = c.ords[::3], c.ords[1::3], c.ords[2::3]

        assert(len(c.times) == len(c.ords))

        return c

    def num_components(self):
        y = self.ords[0]
        return 1 if type(y) in [float, int] else len(y)

    def shorten_quaternion_paths(self):
        if self.interp != 'LINEAR':
            return

        self.ords = [Vector(y) for y in self.ords]
        for i in range(1, len(self.ords)):
            if self.ords[i - 1].dot(self.ords[i]) < 0:
                self.ords[i] = -self.ords[i]

    def make_fcurves(self, op, action, data_path,
                     transform=lambda x: x,
                     tangent_transform=None
                     ):
        framerate = op.options['framerate']
        if framerate <= 0:
            framerate = bpy.context.scene.render.fps
        times = self.times
        ords = self.ords
        interp = self.interp
        bl_interp = {
            'STEP': 'CONSTANT',
            'LINEAR': 'LINEAR',
            'CUBICSPLINE': 'BEZIER',
        }[interp]

        num_components = self.num_components()
        if type(data_path) == list:
            assert(len(data_path) == num_components)
            fcurves = [
                action.fcurves.new(data_path=path, index=index)
                for path, index in data_path
            ]
        else:
            fcurves = [
                action.fcurves.new(data_path=data_path, index=i)
                for i in range(0, num_components)
            ]

        for fcurve in fcurves:
            fcurve.keyframe_points.add(len(times))

        ords = [transform(y) for y in ords]

        # tmp is an array laid out like
        #
        #   [frame, ordinate, frame, ordinate, ...]
        #
        # This let's us set all the keyframes points in one batch, which is fast.
        tmp = [0] * (2 * len(times))
        tmp[::2] = (framerate * t for t in times)
        for i in range(0, num_components):
            if num_components == 1:
                tmp[1::2] = ords
            else:
                tmp[1::2] = (y[i] for y in ords)
            fcurves[i].keyframe_points.foreach_set('co', tmp)

        for fcurve in fcurves:
            for pt in fcurve.keyframe_points:
                pt.interpolation = bl_interp

        if interp == 'CUBICSPLINE':
            if not tangent_transform:
                tangent_transform = transform

            # Blender appears to do Hermite spline interpolation of the _graph_
            # between the points (t1, y1) and (t2, y2), unlike glTF which does
            # interpolation only of the _ordinates_ y1 and y2. So if this is the
            # interval between two keyframes at times t1 and t2 with control
            # points C1 and C2
            #
            #                               o C2: (ct2, cy2)
            #    C1: (ct1, cy1) o            \
            #                  /              * P2: (t1, y1)
            #                 /
            #   P1: (t1, y1) *
            #
            # glTF gives us the right derivative at P1, b (= the slope of the
            # line P1 C1) and the left derivative at P2, a (= the slope of the
            # line P2 C2). So once we pick ct1 and ct2, cy1 and cy2 follow.
            #
            # We pick ct1 and ct2 so that spline interpolation in the
            # t-direction reduces to just linear interpolation.

            for k in range(0, len(times) - 1):
                t1, t2 = times[k], times[k + 1]
                b, a = self.outs[k], self.ins[k + 1]
                a, b = tangent_transform(a), tangent_transform(b)
                if num_components == 1:
                    a, b = (a,), (b,)

                ct1 = (2 * t1 + t2) / 3
                ct2 = (t1 + 2 * t2) / 3

                for i in range(0, num_components):
                    pt1 = fcurves[i].keyframe_points[k]
                    pt1.handle_right_type = 'FREE'
                    pt1.handle_right = ct1 * framerate, pt1.co[1] + (ct1 - t1) * b[i]

                    pt2 = fcurves[i].keyframe_points[k + 1]
                    pt2.handle_left_type = 'FREE'
                    pt2.handle_left = ct2 * framerate, pt2.co[1] + (ct2 - t2) * a[i]

        for fcurve in fcurves:
            fcurve.update()

        return fcurves
