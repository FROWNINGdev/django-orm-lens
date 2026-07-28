from .models import Post


def recent(request):
    return Post.objects.filter(author__id=request.user.id).order_by("-author")
