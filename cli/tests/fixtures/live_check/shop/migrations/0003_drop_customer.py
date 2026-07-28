from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("shop", "0002_drop_reference")]
    operations = [
        migrations.RemoveField(model_name="order", name="customer"),
    ]
