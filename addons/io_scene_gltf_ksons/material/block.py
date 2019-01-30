from mathutils import Vector

# A _block_ is either a shader node or a rectangular set of smaller blocks
# represented by the Block class. We can line blocks up in rows, etc. So we use
# them to make node trees look nice.


class Block:
    def __init__(self, *blocks):
        self.children = []
        # Bounding box of children
        self.top_left = Vector((0, 0))
        self.bottom_right = Vector((0, 0))

        for block in blocks:
            self.add(block)

    def add(self, child):
        self.children.append(child)
        if len(self.children) == 1:
            self.top_left = top_left(child)
            self.bottom_right = bottom_right(child)
        else:
            tl = top_left(child)
            br = bottom_right(child)
            self.top_left = Vector((
                min(self.top_left[0], tl[0]),
                max(self.top_left[1], tl[1]),
            ))
            self.bottom_right = Vector((
                max(self.bottom_right[0], br[0]),
                min(self.bottom_right[1], br[1]),
            ))

    def move_by(self, delta):
        for child in self.children:
            move_by(child, delta)
        self.top_left += delta
        self.bottom_right += delta

    @staticmethod
    # Creates an empty block (used for spacing purposes)
    def empty(width=100, height=140):
        block = Block()
        block.bottom_right = Vector((width, -height))
        return block

    @staticmethod
    # Aligns the blocks in a center-aligned row. Returns a new Block containing
    # the blocks.
    #       .--.         .---.
    #       |  | .-----. |   |
    #     --|A |-|  B  |-| C |--
    #       |  | '-----' |   |
    #       '--'         '---'
    def row_align_center(blocks, gutter=100):
        x, y = 0, 0
        max_height = max((height(block) for block in blocks), default=0)
        for block in blocks:
            w, h = width(block), height(block)
            dh = (max_height - h) / 2
            move_to(block, Vector((x, y - dh)))
            x += w + gutter

        return Block(*blocks)

    @staticmethod
    # Aligns the blocks in a right-aligned column. Returns a new Block
    # containing the blocks.
    #        .--.
    #        | A|
    #        '--'
    #     .-----.
    #     |  B  |
    #     '-----'
    #       .---.
    #       | C |
    #       '---'
    def col_align_right(blocks, gutter=100):
        x, y = 0, 0
        max_width = max((width(block) for block in blocks), default=0)
        for block in blocks:
            w, h = width(block), height(block)
            dw = max_width - w
            move_to(block, Vector((x + dw, y)))
            y -= h + gutter

        return Block(*blocks)


def top_left(block):
    if type(block) == Block:
        return block.top_left
    return Vector(block.location)


def bottom_right(block):
    if type(block) == Block:
        return Vector(block.bottom_right)
    return block.location + Vector((block.width, -block.height))


def move_by(block, delta):
    if type(block) == Block:
        block.move_by(delta)
    else:
        block.location += delta


def width(block):
    tl = top_left(block)
    br = bottom_right(block)
    return br[0] - tl[0]


def height(block):
    tl = top_left(block)
    br = bottom_right(block)
    return tl[1] - br[1]


def move_to(block, pos):
    delta = pos - top_left(block)
    move_by(block, delta)


def center_at_origin(block):
    w, h = width(block), height(block)
    move_to(block, Vector((-w/2, h/2)))
