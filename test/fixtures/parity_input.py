from django.db import models

class Author(models.Model):
    name = models.CharField(max_length=100)


class Book(models.Model):
    title = models.CharField(max_length=200)
    author = models.ForeignKey('Author', on_delete=models.CASCADE, related_name='books')
    editor = models.OneToOneField('Author', on_delete=models.SET_NULL, related_name='edited_book')
    tags = models.ManyToManyField('Tag', through='BookTag')

    class Meta:
        ordering = ['title']


class Tag(models.Model):
    name = models.SlugField()


class BookTag(models.Model):
    book = models.ForeignKey('Book', on_delete=models.CASCADE)
    tag = models.ForeignKey('Tag', on_delete=models.CASCADE)


# A project-local abstract base and a concrete subclass of it. Present because
# both parsers were green on this fixture while disagreeing about exactly this
# shape: the TypeScript side did not recognise `Chapter` as a model at all,
# and neither suite could see that, because the fixture had no local base in
# it. `class X(SomeLocalBase)` is about as common as Django patterns get.
class Auditable(models.Model):
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Chapter(Auditable):
    heading = models.CharField(max_length=120)
    book = models.ForeignKey('Book', on_delete=models.CASCADE, related_name='chapters')
    updated = models.CharField(max_length=10)
