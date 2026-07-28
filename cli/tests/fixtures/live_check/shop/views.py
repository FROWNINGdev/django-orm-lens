from .models import Order


def recent(request):
    return Order.objects.filter(customer__id=request.user.id).order_by("-reference")
