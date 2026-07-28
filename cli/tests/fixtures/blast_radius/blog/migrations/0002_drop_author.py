from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("blog", "0001_initial")]
    operations = [
        migrations.RemoveField(model_name="post", name="author"),
    ]
