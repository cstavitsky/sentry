from django.db.models.fields import BigIntegerField

from bitfield.query import BitQueryExactLookupStub
from bitfield.types import Bit, BitHandler

# Count binary capacity. Truncate "0b" prefix from binary form.
# Twice faster than bin(i)[2:] or math.floor(math.log(i))
MAX_FLAG_COUNT = int(len(bin(BigIntegerField.MAX_BIGINT)) - 2)


class BitFieldFlags:
    def __init__(self, flags):
        if len(flags) > MAX_FLAG_COUNT:
            raise ValueError("Too many flags")
        self._flags = flags

    def __repr__(self):
        return repr(self._flags)

    def __iter__(self):
        yield from self._flags

    def __getattr__(self, key):
        if key not in self._flags:
            raise AttributeError
        return Bit(self._flags.index(key))

    __getitem__ = __getattr__

    def iteritems(self):
        for flag in self._flags:
            yield flag, Bit(self._flags.index(flag))

    def iterkeys(self):
        yield from self._flags

    def itervalues(self):
        for flag in self._flags:
            yield Bit(self._flags.index(flag))

    def items(self):
        return list(self.iteritems())  # NOQA

    def keys(self):
        return list(self.iterkeys())  # NOQA

    def values(self):
        return list(self.itervalues())  # NOQA


class BitFieldCreator:
    """
    A placeholder class that provides a way to set the attribute on the model.
    Descriptor for BitFields.  Checks to make sure that all flags of the
    instance match the class.  This is to handle the case when caching
    an older version of the instance and a newer version of the class is
    available (usually during deploys).
    """

    def __init__(self, field):
        self.field = field

    def __set__(self, obj, value):
        obj.__dict__[self.field.name] = self.field.to_python(value)

    def __get__(self, obj, type=None):
        if obj is None:
            return BitFieldFlags(self.field.flags)
        retval = obj.__dict__[self.field.name]
        if self.field.__class__ is BitField:
            # Update flags from class in case they've changed.
            retval._keys = self.field.flags
        return retval


class BitField(BigIntegerField):
    def contribute_to_class(self, cls, name, **kwargs):
        super().contribute_to_class(cls, name, **kwargs)
        setattr(cls, self.name, BitFieldCreator(self))

    def __init__(self, flags, default=None, *args, **kwargs):
        if isinstance(flags, dict):
            # Get only integer keys in correct range
            valid_keys = (
                k for k in flags.keys() if isinstance(k, int) and (0 <= k < MAX_FLAG_COUNT)
            )
            if not valid_keys:
                raise ValueError("Wrong keys or empty dictionary")
            # Fill list with values from dict or with empty values
            flags = [flags.get(i, "") for i in range(max(valid_keys) + 1)]

        if len(flags) > MAX_FLAG_COUNT:
            raise ValueError("Too many flags")

        self._arg_flags = flags
        flags = list(flags)
        labels = []
        for num, flag in enumerate(flags):
            if isinstance(flag, (tuple, list)):
                flags[num] = flag[0]
                labels.append(flag[1])
            else:
                labels.append(flag)

        if isinstance(default, (list, tuple, set, frozenset)):
            new_value = 0
            for flag in default:
                new_value |= Bit(flags.index(flag))
            default = new_value

        BigIntegerField.__init__(self, default=default, *args, **kwargs)
        self.flags = flags
        self.labels = labels

    def pre_save(self, instance, add):
        value = getattr(instance, self.attname)
        return value

    def get_prep_value(self, value):
        if value is None:
            return None
        if isinstance(value, (BitHandler, Bit)):
            value = value.mask
        return int(value)

    def to_python(self, value):
        if isinstance(value, Bit):
            value = value.mask
        if not isinstance(value, BitHandler):
            # Regression for #1425: fix bad data that was created resulting
            # in negative values for flags.  Compute the value that would
            # have been visible ot the application to preserve compatibility.
            if isinstance(value, int) and value < 0:
                new_value = 0
                for bit_number, _ in enumerate(self.flags):
                    new_value |= value & (2**bit_number)
                value = new_value

            value = BitHandler(value, self.flags, self.labels)
        else:
            # Ensure flags are consistent for unpickling
            value._keys = self.flags
        return value

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        args.insert(0, self._arg_flags)
        return name, path, args, kwargs


class TypedBitfieldMeta(type):
    def __new__(cls, name, bases, clsdict):
        if name == "TypedBitfield":
            return type.__new__(cls, name, bases, clsdict)

        flags = []
        for attr, ty in clsdict["__annotations__"].items():
            if attr.startswith("_"):
                continue

            if attr in ("bitfield_default", "bitfield_null"):
                continue

            assert ty in ("bool", bool), f"bitfields can only hold bools, {attr} is {ty!r}"
            flags.append(attr)

        return BitField(
            flags=flags,
            default=clsdict.get("bitfield_default"),
            null=clsdict.get("bitfield_null") or False,
        )

    def __int__(self) -> int:
        raise NotImplementedError()


class TypedBitfield(metaclass=TypedBitfieldMeta):
    pass


BitField.register_lookup(BitQueryExactLookupStub)
