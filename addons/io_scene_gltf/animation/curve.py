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
            c.ins, c.ords, c.outs = (
                [c.ords[i] for i in range(0, len(c.ords), 3)],
                [c.ords[i] for i in range(1, len(c.ords), 3)],
                [c.ords[i] for i in range(2, len(c.ords), 3)],
            )

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
        framerate = op.framerate
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

        # Let's us uniformly handle ordinates that are sequences and ordinates
        # that are scalars.
        if num_components == 1:
            def tup(x): return (x,)
        else:
            def tup(x): return x

        for k, (t, y) in enumerate(zip(times, ords)):
            t = t * framerate
            y = tup(transform(y))
            for i in range(0, num_components):
                pt = fcurves[i].keyframe_points[k]
                pt.interpolation = bl_interp
                pt.co = (t, y[i])

        if interp == 'CUBICSPLINE':
            if not tangent_transform:
                tangent_transform = transform

            for k, (t, a, b) in enumerate(zip(times, self.ins, self.outs)):
                t = t * framerate
                a, b = tup(tangent_transform(a)), tup(tangent_transform(b))
                for i in range(0, num_components):
                    pt = fcurves[i].keyframe_points[k]
                    pt.handle_left_type = 'FREE'
                    pt.handle_right_type = 'FREE'
                    # TODO: set tangents somehow
                    # pt.handle_left = ?
                    # pt.handle_right = ?

        for fcurve in fcurves:
            fcurve.update()

        return fcurves
