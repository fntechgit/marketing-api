from django.db import connection


class ConfigValuesService:

    def clone_from_to(self, from_show_id:int, to_show_id:int):
        with connection.cursor() as cursor:
            res = cursor.execute("""INSERT INTO config_values (created,modified,`key`,type,value,file,show_id) 
                                 SELECT now(),now(),`key`,type,value,file,%s FROM config_values AS CV 
                                 WHERE CV.show_id = %s AND
                                 NOT EXISTS (
                                    SELECT 1 FROM config_values WHERE config_values.`key`= CV.`key` 
                                    AND config_values.show_id = %s
                                 ); 
                                 """,
                                 [to_show_id, from_show_id, to_show_id])
        return res