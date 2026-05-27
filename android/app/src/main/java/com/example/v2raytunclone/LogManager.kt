package com.example.v2raytunclone

import androidx.compose.runtime.mutableStateListOf
import java.io.BufferedReader
import java.io.InputStreamReader
import java.util.concurrent.atomic.AtomicBoolean

data class LogLine(
    val original: String,
    val time: String,
    val level: String, // "V", "D", "I", "W", "E", "F"
    val tag: String,
    val message: String
)

object LogManager {
    private val _logs = mutableStateListOf<LogLine>()
    val logs: List<LogLine> get() = _logs

    private val isRunning = AtomicBoolean(false)
    private var logcatProcess: Process? = null
    private var readerThread: Thread? = null

    fun startLogging() {
        if (!isRunning.compareAndSet(false, true)) {
            return // Уже запущено
        }

        readerThread = Thread {
            val pid = android.os.Process.myPid()
            val command = arrayOf("logcat", "-v", "time", "--pid=$pid")
            
            try {
                logcatProcess = Runtime.getRuntime().exec(command)
                val reader = BufferedReader(InputStreamReader(logcatProcess!!.inputStream))
                
                // Регулярное выражение для парсинга вывода logcat -v time
                // Пример: 05-22 12:55:38.467 I/GoLog( 1399): message
                // Либо: 05-22 12:55:38.467  1399  2132 I GoLog   : message
                val regex = """^(\d{2}-\d{2}\s\d{2}:\d{2}:\d{2}\.\d{3})\s+(\d+)\s+(\d+)\s+([VDIWEF])\s+([^:]+):\s(.*)$""".toRegex()

                var line: String? = null
                while (isRunning.get() && reader.readLine().also { line = it } != null) {
                    val currentLine = line ?: continue
                    val logLine = parseLine(currentLine, regex)
                    
                    // Добавляем лог в список в главном потоке Compose
                    synchronized(_logs) {
                        if (_logs.size > 1500) {
                            _logs.removeAt(0)
                        }
                        _logs.add(logLine)
                    }
                }
            } catch (e: Exception) {
                val errorLog = LogLine(
                    original = "Error: ${e.message}",
                    time = "",
                    level = "E",
                    tag = "LogManager",
                    message = "Ошибка чтения logcat: ${e.message}"
                )
                synchronized(_logs) {
                    _logs.add(errorLog)
                }
            } finally {
                isRunning.set(false)
            }
        }.apply {
            isDaemon = true
            name = "LogcatReaderThread"
            start()
        }
    }

    private fun parseLine(line: String, regex: Regex): LogLine {
        try {
            val match = regex.matchEntire(line)
            if (match != null) {
                val (time, pid, tid, level, tag, msg) = match.destructured
                return LogLine(
                    original = line,
                    time = time,
                    level = level,
                    tag = tag.trim(),
                    message = msg
                )
            }
            
            // Запасной парсинг для альтернативного формата: 05-22 12:55:38.467 I/GoLog(1399): message
            val altRegex = """^(\d{2}-\d{2}\s\d{2}:\d{2}:\d{2}\.\d{3})\s+([VDIWEF])/([^\(]+)\((\d+)\):\s(.*)$""".toRegex()
            val altMatch = altRegex.matchEntire(line)
            if (altMatch != null) {
                val (time, level, tag, pid, msg) = altMatch.destructured
                return LogLine(
                    original = line,
                    time = time,
                    level = level,
                    tag = tag.trim(),
                    message = msg
                )
            }
        } catch (e: Exception) {
            // Игнорируем и отдаем дефолт
        }
        
        // Если не распарсилось, ищем уровень логирования
        var level = "I"
        if (line.contains(" E/") || line.contains("Error") || line.contains("ОШИБКА")) {
            level = "E"
        } else if (line.contains(" W/") || line.contains("Warning") || line.contains("Внимание")) {
            level = "W"
        } else if (line.contains(" D/") || line.contains("Debug")) {
            level = "D"
        }
        
        return LogLine(
            original = line,
            time = "",
            level = level,
            tag = "System",
            message = line
        )
    }

    fun stopLogging() {
        isRunning.set(false)
        logcatProcess?.destroy()
        logcatProcess = null
        readerThread = null
    }

    fun clearLogs() {
        synchronized(_logs) {
            _logs.clear()
        }
    }
}
