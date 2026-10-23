package com.meetingnotes.app.ui

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Mic
import androidx.compose.material.icons.filled.Notes
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.navigation.NavGraph.Companion.findStartDestination
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import com.meetingnotes.app.MeetingApp

@Composable
fun AppRoot() {
    val context = LocalContext.current
    val container = (context.applicationContext as MeetingApp).container
    var paired by remember { mutableStateOf(container.settings.isPaired) }

    if (!paired) {
        PairingScreen(
            initialServerUrl = container.settings.serverUrl,
            onPaired = { paired = true },
        )
    } else {
        MainScaffold(onUnpaired = { paired = false })
    }
}

private data class Tab(
    val route: String,
    val label: String,
    val icon: androidx.compose.ui.graphics.vector.ImageVector,
)

private val tabs = listOf(
    Tab("record", "录音", Icons.Filled.Mic),
    Tab("notes", "笔记", Icons.Filled.Notes),
    Tab("settings", "设置", Icons.Filled.Settings),
)

@Composable
private fun MainScaffold(onUnpaired: () -> Unit) {
    val context = LocalContext.current
    val container = (context.applicationContext as MeetingApp).container
    val updateState by container.updates.state.collectAsState()
    var dismissedVersion by rememberSaveable { mutableIntStateOf(0) }
    val navController = rememberNavController()
    val backStackEntry by navController.currentBackStackEntryAsState()
    val currentRoute = backStackEntry?.destination?.route
    val showBottomBar = tabs.any { it.route == currentRoute }

    LaunchedEffect(Unit) {
        container.updates.check()
    }

    Scaffold(
        bottomBar = {
            if (showBottomBar) {
                NavigationBar {
                    tabs.forEach { tab ->
                        NavigationBarItem(
                            selected = currentRoute == tab.route,
                            onClick = {
                                navController.navigate(tab.route) {
                                    popUpTo(navController.graph.findStartDestination().id) {
                                        saveState = true
                                    }
                                    launchSingleTop = true
                                    restoreState = true
                                }
                            },
                            icon = { Icon(tab.icon, contentDescription = tab.label) },
                            label = { Text(tab.label) },
                        )
                    }
                }
            }
        }
    ) { innerPadding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(innerPadding),
        ) {
            val release = updateState.release
            if (
                release != null &&
                updateState.apk == null &&
                release.versionCode != dismissedVersion
            ) {
                Card(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(start = 16.dp, end = 16.dp, top = 12.dp),
                    colors = CardDefaults.cardColors(
                        containerColor = MaterialTheme.colorScheme.primaryContainer,
                    ),
                ) {
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(start = 16.dp, top = 8.dp, end = 8.dp, bottom = 8.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Column(modifier = Modifier.weight(1f)) {
                            Text(
                                "发现新版本 ${release.versionName}",
                                style = MaterialTheme.typography.titleSmall,
                            )
                            Text(
                                "可在设置中下载并安装",
                                style = MaterialTheme.typography.bodySmall,
                            )
                        }
                        TextButton(onClick = { navController.navigate("settings") }) {
                            Text("更新")
                        }
                        TextButton(onClick = { dismissedVersion = release.versionCode }) {
                            Text("稍后")
                        }
                    }
                }
            }
            NavHost(
                navController = navController,
                startDestination = "record",
                modifier = Modifier.weight(1f),
            ) {
                composable("record") { RecordScreen() }
                composable("notes") {
                    NotesScreen(onOpenNote = { jobId -> navController.navigate("note/$jobId") })
                }
                composable("settings") {
                    SettingsScreen(onUnpaired = onUnpaired)
                }
                composable("note/{jobId}") { entry ->
                    val jobId = entry.arguments?.getString("jobId").orEmpty()
                    NoteDetailScreen(
                        jobId = jobId,
                        onBack = { navController.popBackStack() },
                    )
                }
            }
        }
    }
}
