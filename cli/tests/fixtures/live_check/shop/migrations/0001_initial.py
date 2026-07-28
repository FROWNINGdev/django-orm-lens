from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies = []
    operations = [
        migrations.CreateModel(
            name="Order",
            fields=[
                ("id", models.AutoField(primary_key=True)),
                ("reference", models.CharField(max_length=32)),
                ("customer", models.ForeignKey("auth.User", on_delete=models.CASCADE)),
            ],
        ),
    ]
