from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("shop", "0001_initial")]
    operations = [
        migrations.RemoveField(model_name="order", name="reference"),
    ]
