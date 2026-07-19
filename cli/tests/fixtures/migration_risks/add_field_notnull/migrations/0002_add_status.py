from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("orders", "0001_initial")]
    operations = [
        migrations.AddField(
            model_name="order",
            name="status",
            field=models.CharField(max_length=20),
        ),
    ]
