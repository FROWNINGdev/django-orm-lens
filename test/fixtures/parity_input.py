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
