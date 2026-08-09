"""django-mptt fixture — MPTTModel base plus all three Tree* relation fields.

Nothing here is imported at parse time: the parser is purely static, so this
file only has to *look* like a django-mptt app, not be installable. Shapes are
taken from django-mptt's own documentation.

`class MPTTMeta` is deliberately present. It must not be mistaken for
`class Meta` — the parser's META_START_RE matches the literal name `Meta`, and
a fixture is the cheapest place to keep that honest.
"""

from django.db import models
from mptt.fields import TreeForeignKey, TreeManyToManyField, TreeOneToOneField
from mptt.models import MPTTModel


class Category(MPTTModel):
    name = models.CharField(max_length=50)
    parent = TreeForeignKey(
        'self',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='children',
    )

    class MPTTMeta:
        order_insertion_by = ['name']

    class Meta:
        verbose_name_plural = 'categories'


class Genre(MPTTModel):
    title = models.CharField(max_length=80)
    parent = TreeForeignKey('self', on_delete=models.SET_NULL, null=True)
    canonical = TreeOneToOneField(
        'Category',
        on_delete=models.PROTECT,
        related_name='canonical_genre',
    )
    tags = TreeManyToManyField('Category', related_name='genres')
