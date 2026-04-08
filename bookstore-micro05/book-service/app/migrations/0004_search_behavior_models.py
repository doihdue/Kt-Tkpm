from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('app', '0003_category_book_category'),
    ]

    operations = [
        migrations.CreateModel(
            name='SearchBehaviorEvent',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('customer_id', models.IntegerField(db_index=True)),
                ('event_type', models.CharField(db_index=True, max_length=32)),
                ('query', models.CharField(blank=True, max_length=255)),
                ('book_id', models.IntegerField(blank=True, db_index=True, null=True)),
                ('book_ids', models.JSONField(blank=True, default=list)),
                ('metadata', models.JSONField(blank=True, default=dict)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='SearchUserProfile',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('customer_id', models.IntegerField(unique=True)),
                ('token_weights', models.JSONField(blank=True, default=dict)),
                ('book_weights', models.JSONField(blank=True, default=dict)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
        ),
    ]
